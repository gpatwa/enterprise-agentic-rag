# services/api/app/secrets_refresh.py
"""
Re-read provider API keys from the secrets vault so a rotated key takes effect without a restart.

At start the API injects keys from the vault into ``settings`` (main.py). A key someone rotates later would otherwise
sit unused until the pods restart. This refresher re-reads the vault on an interval; when a value changed it updates
``settings`` and asks each key-based client to rebuild its SDK client (``refresh_credentials``).

Only keys that were NOT supplied as environment variables are refreshed: an environment variable is an explicit
operator choice and the vault is not allowed to override it. Keyless providers (azure_openai) have nothing to refresh.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# settings attribute -> vault secret name (the provider keys only; the same names main.py injects at start)
PROVIDER_KEY_SECRETS = {
    "OPENAI_API_KEY": "openai-api-key",
    "GOOGLE_API_KEY": "gemini-api-key",
    "TAVILY_API_KEY": "tavily-api-key",
}


class ProviderKeyRefresher:
    def __init__(
        self,
        secrets_client,
        settings_obj,
        clients: Iterable[object],
        env_provided: Iterable[str],
        interval_seconds: int,
    ) -> None:
        self._secrets = secrets_client
        self._settings = settings_obj
        self._clients = [c for c in clients if c is not None]
        self._env_provided = set(env_provided)
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task] = None

    async def refresh_once(self) -> list[str]:
        """Re-read the vault once. Returns the settings attributes whose value changed."""
        changed: list[str] = []
        for attr, vault_key in PROVIDER_KEY_SECRETS.items():
            if attr in self._env_provided:
                continue
            try:
                value = await self._secrets.get_secret(vault_key)
            except Exception as exc:  # a vault outage must not take the API down; keep the key in use
                logger.warning("Key refresh: could not read '%s' (%s); keeping the current key", vault_key, type(exc).__name__)
                continue
            if value and value != getattr(self._settings, attr, None):
                object.__setattr__(self._settings, attr, value)
                changed.append(attr)
                logger.info("Key refresh: %s changed in the vault; applying", attr)
        if changed:
            for client in self._clients:
                refresh = getattr(client, "refresh_credentials", None)
                if refresh is None:
                    continue
                try:
                    await refresh()
                except Exception as exc:
                    logger.error("Key refresh: %s failed to apply the new key (%s)", type(client).__name__, exc)
        return changed

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Key refresh iteration failed")

    def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._run(), name="provider-key-refresh")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
