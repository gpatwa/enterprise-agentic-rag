"""A provider key rotated in the vault takes effect without a restart.

The API injects keys from the vault at start. ``ProviderKeyRefresher`` re-reads them on an interval and rebuilds the
key-based clients when one changed. Keys given as environment variables are explicit and are never overridden, a vault
outage keeps the key in use, and keyless providers have nothing to refresh.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.secrets_refresh import PROVIDER_KEY_SECRETS, ProviderKeyRefresher


def _run(coro):
    return asyncio.run(coro)


class _Vault:
    def __init__(self, values: dict[str, str | Exception | None]) -> None:
        self.values = values

    async def get_secret(self, name: str):
        value = self.values.get(name)
        if isinstance(value, Exception):
            raise value
        return value


class _Client:
    def __init__(self, fail: bool = False) -> None:
        self.refreshed, self.fail = 0, fail

    async def refresh_credentials(self) -> None:
        self.refreshed += 1
        if self.fail:
            raise RuntimeError("boom")


def _refresher(vault, settings=None, clients=(), env_provided=(), interval=300):
    settings = settings or SimpleNamespace(OPENAI_API_KEY="old-openai", GOOGLE_API_KEY=None, TAVILY_API_KEY=None)
    return ProviderKeyRefresher(vault, settings, clients, env_provided, interval), settings


def test_a_rotated_key_is_applied_and_the_clients_rebuild_once() -> None:
    client = _Client()
    refresher, settings = _refresher(_Vault({"openai-api-key": "new-openai"}), clients=[client])
    assert _run(refresher.refresh_once()) == ["OPENAI_API_KEY"]
    assert settings.OPENAI_API_KEY == "new-openai" and client.refreshed == 1


def test_an_unchanged_key_does_nothing() -> None:
    client = _Client()
    refresher, _ = _refresher(_Vault({"openai-api-key": "old-openai"}), clients=[client])
    assert _run(refresher.refresh_once()) == []
    assert client.refreshed == 0


def test_a_key_that_first_appears_later_is_picked_up() -> None:
    client = _Client()
    refresher, settings = _refresher(_Vault({"gemini-api-key": "first-gemini"}), clients=[client])
    assert _run(refresher.refresh_once()) == ["GOOGLE_API_KEY"] and settings.GOOGLE_API_KEY == "first-gemini"


def test_keys_from_the_environment_are_never_overridden() -> None:
    client = _Client()
    refresher, settings = _refresher(
        _Vault({"openai-api-key": "from-vault"}), clients=[client], env_provided={"OPENAI_API_KEY"}
    )
    assert _run(refresher.refresh_once()) == []
    assert settings.OPENAI_API_KEY == "old-openai" and client.refreshed == 0


def test_a_vault_outage_keeps_the_key_in_use_and_does_not_raise() -> None:
    client = _Client()
    refresher, settings = _refresher(_Vault({"openai-api-key": ConnectionError("vault down")}), clients=[client])
    assert _run(refresher.refresh_once()) == []
    assert settings.OPENAI_API_KEY == "old-openai" and client.refreshed == 0


def test_an_empty_vault_value_never_wipes_a_working_key() -> None:
    refresher, settings = _refresher(_Vault({"openai-api-key": ""}))
    assert _run(refresher.refresh_once()) == [] and settings.OPENAI_API_KEY == "old-openai"


def test_a_client_that_fails_to_rebuild_does_not_stop_the_others_or_raise() -> None:
    bad, good, keyless = _Client(fail=True), _Client(), object()
    refresher, _ = _refresher(_Vault({"openai-api-key": "new"}), clients=[bad, keyless, good, None])
    assert _run(refresher.refresh_once()) == ["OPENAI_API_KEY"]
    assert bad.refreshed == 1 and good.refreshed == 1


def test_the_refresher_covers_exactly_the_provider_keys_the_app_reads_from_the_vault() -> None:
    assert PROVIDER_KEY_SECRETS == {
        "OPENAI_API_KEY": "openai-api-key",
        "GOOGLE_API_KEY": "gemini-api-key",
        "TAVILY_API_KEY": "tavily-api-key",
    }


def test_the_loop_refreshes_on_the_interval_and_stops_cleanly() -> None:
    async def scenario() -> int:
        vault = _Vault({"openai-api-key": "k1"})
        refresher, settings = _refresher(vault, interval=1)
        refresher._interval = 0.01  # tight loop for the test
        refresher.start()
        await asyncio.sleep(0.1)
        vault.values["openai-api-key"] = "k2"
        await asyncio.sleep(0.1)
        await refresher.stop()
        assert settings.OPENAI_API_KEY == "k2"
        return 1

    assert _run(scenario()) == 1


def test_a_zero_interval_starts_no_task() -> None:
    async def scenario() -> bool:
        refresher, _ = _refresher(_Vault({}), interval=0)
        refresher.start()
        return refresher._task is None

    assert _run(scenario())


# ----- the real key-based clients rebuild around the new key ---------------------------------------------------------------


def test_the_openai_clients_rebuild_with_the_rotated_key(monkeypatch) -> None:
    from app.clients.openai_embed import OpenAIEmbedClient
    from app.clients.openai_llm import OpenAILLMClient
    from app.config import settings

    async def scenario() -> None:
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-old")
        for client in (OpenAILLMClient(), OpenAIEmbedClient()):
            await client.start()
            assert client.client.api_key == "sk-old"
            monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-new")
            await client.refresh_credentials()
            assert client.client.api_key == "sk-new"
            await client.close()
            monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-old")

    _run(scenario())


def test_main_starts_and_stops_the_refresher_and_remembers_environment_keys() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "main.py").read_text()
    assert "ProviderKeyRefresher(" in source and "_key_refresher.start()" in source
    assert "await _key_refresher.stop()" in source
    assert "_env_provided_keys = {a for a in PROVIDER_KEY_SECRETS if getattr(settings, a, None)}" in source
