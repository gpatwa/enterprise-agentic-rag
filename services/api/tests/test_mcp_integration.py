# services/api/tests/test_mcp_integration.py
"""
Phase-2 MCP integration tests — proof of the full rails against a real
subprocess.

Skip gates (every test honours all three)
-----------------------------------------
- env var `MCP_INTEGRATION_TESTS != "1"`     → skipped
- `node` / `npx` not on PATH                 → skipped
- the `mcp` Python SDK not installed         → skipped

Why @modelcontextprotocol/server-everything?
--------------------------------------------
It's the canonical credential-free MCP demo server, with 13 stable tools
including `echo` (perfect for assertions) and `get-sum` (verifies arg
serialization). The Tier-1 customer servers (slack/github/notion) all
require auth tokens AND exit before MCP `initialize` if the tokens are
missing — meaning we can't write a CI-runnable integration test against
them without real credentials. Token-gated tests live below those checks
and skip individually if the corresponding token isn't set.

What these tests prove
----------------------
- Real `npx` spawn through our pool succeeds and reaches `initialize()`.
- Tools are listed and namespaced (`{server}.{tool}`) end-to-end.
- A real `call_tool` round-trips through manager → pool → SDK → subprocess
  and the response is parsed into our `ToolCallResult` shape.
- Concurrent first-callers for the same (tenant, server) result in
  exactly one subprocess spawn even when the spawn itself takes seconds.
- `pool.evict()` shuts down the subprocess cleanly.
- Unknown qualified names are rejected by the manager regardless of
  whether the underlying server would have accepted them.

First-run cost
--------------
`npx -y @modelcontextprotocol/server-everything` cold-fetches the package
on the first call (~10-20s on a cold cache). All tests share a single
package install thanks to npx's cache; total suite latency stabilises at
a few seconds once cached.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import Any

import pytest


# ── Skip detection ────────────────────────────────────────────────────


def _skip_reason() -> str | None:
    if os.environ.get("MCP_INTEGRATION_TESTS") != "1":
        return "MCP_INTEGRATION_TESTS != 1 (set to opt in)"
    if not shutil.which("npx") or not shutil.which("node"):
        return "node/npx not on PATH"
    try:
        import mcp  # noqa: F401
    except ImportError:
        return "mcp SDK not installed (pip install 'mcp>=1.1.0')"
    return None


_SKIP = _skip_reason()
pytestmark = pytest.mark.skipif(_SKIP is not None, reason=_SKIP or "")


EVERYTHING_NPX_PACKAGE = "@modelcontextprotocol/server-everything"
EVERYTHING_SERVER_NAME = "_test_everything"  # underscore avoids catalog collisions


# ── Reusable fixtures ─────────────────────────────────────────────────


@pytest.fixture
def everything_in_catalog():
    """Register the demo server in the catalog for the duration of one test."""
    from app.mcp.catalog import MCPCatalog
    from app.mcp.types import MCPCatalogEntry

    entry = MCPCatalogEntry(
        server_name=EVERYTHING_SERVER_NAME,
        display_name="MCP Everything (test)",
        description="Demo server with echo + get-sum etc. No auth required.",
        npx_package=EVERYTHING_NPX_PACKAGE,
        required_credentials=(),
    )
    MCPCatalog._register(entry)
    yield entry
    MCPCatalog._unregister(EVERYTHING_SERVER_NAME)


class _InMemoryStorage:
    """Minimal in-memory replacement for app.mcp.storage."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}

    async def list_for_tenant(self, _s, tenant_id, *, only_enabled=False):
        out = [r for k, r in self.rows.items() if k[0] == tenant_id]
        if only_enabled:
            out = [r for r in out if r["status"] == "enabled"]
        return out

    async def get(self, _s, tenant_id, server_name, *, decrypt=False):
        row = self.rows.get((tenant_id, server_name))
        if row is None:
            return None
        out = dict(row)
        if decrypt:
            out["credentials"] = row.get("_creds", {})
        return out

    async def upsert(self, _s, *, tenant_id, server_name, credentials, status):
        self.rows[(tenant_id, server_name)] = {
            "id": len(self.rows) + 1,
            "tenant_id": tenant_id,
            "server_name": server_name,
            "status": status.value,
            "_creds": credentials,
            "error_message": None,
            "last_health_check": None,
            "created_at": "2026-05-04T00:00:00Z",
            "updated_at": "2026-05-04T00:00:00Z",
        }
        row = self.rows[(tenant_id, server_name)]
        return {k: v for k, v in row.items() if not k.startswith("_")}

    async def set_status(
        self, _s, *, tenant_id, server_name,
        status, error_message=None, health_check_now=False,
    ):
        row = self.rows.get((tenant_id, server_name))
        if row is None:
            return False
        row["status"] = status.value
        row["error_message"] = error_message
        return True

    async def remove(self, _s, *, tenant_id, server_name):
        return self.rows.pop((tenant_id, server_name), None) is not None


@pytest.fixture
async def real_manager(monkeypatch):
    """
    A real MCPManager + MCPProcessPool wired to in-memory storage.

    Async-yield fixture so teardown can await pool.stop() in the same
    asyncio loop that opened the sessions. The mcp SDK's stdio_client
    uses anyio cancel scopes that complain if exited from a different
    task than the one that entered them — this fixture pattern keeps
    setup, body, and teardown on the same task.
    """
    from app.mcp import storage as storage_mod
    from app.mcp.crypto import init_cipher, reset_cipher, generate_key
    from app.mcp.manager import MCPManager
    from app.mcp.process_pool import MCPProcessPool

    reset_cipher()
    init_cipher(generate_key())
    fake = _InMemoryStorage()
    for fn in ("list_for_tenant", "get", "upsert", "set_status", "remove"):
        monkeypatch.setattr(storage_mod, fn, getattr(fake, fn), raising=True)

    # Real pool — no factory injection. Uses real stdio_client + ClientSession.
    # Generous timeout because cold npx warm-up can hit ~30s on first call.
    pool = MCPProcessPool(
        max_processes=10,
        idle_seconds=None,
        tool_timeout_seconds=60,
    )
    mgr = MCPManager()
    mgr.configure(enabled=True, pool=pool, tool_timeout_seconds=60)
    try:
        yield mgr, pool, fake
    finally:
        # Drain the pool in the same task that entered the sessions.
        # If anyio still complains (e.g. on Python 3.12 where loop policy
        # changed), the warning is noisy but the subprocesses do exit.
        try:
            await pool.stop()
        except Exception:
            pass


# ── Smoke: low-level pool against real subprocess ─────────────────────


class TestRealSubprocessSmoke:
    """Bare-metal smoke test that doesn't even use the manager."""

    @pytest.mark.asyncio
    async def test_pool_spawn_initialize_list_call_close(self, everything_in_catalog):
        from app.mcp.catalog import MCPCatalog
        from app.mcp.process_pool import MCPProcessPool

        # Build the StdioServerParameters directly from the catalog entry.
        from mcp import StdioServerParameters

        entry = MCPCatalog.get(EVERYTHING_SERVER_NAME)
        assert entry is not None
        spec = StdioServerParameters(
            command=shutil.which("npx") or "npx",
            args=["-y", entry.npx_package],
            env=dict(os.environ),
        )
        pool = MCPProcessPool(
            max_processes=10, idle_seconds=None, tool_timeout_seconds=60
        )
        try:
            session = await pool.get_session("smoke", EVERYTHING_SERVER_NAME, spec)
            tools = await asyncio.wait_for(session.list_tools(), timeout=15)
            names = {t.name for t in tools.tools}
            assert "echo" in names
            assert "get-sum" in names

            result = await asyncio.wait_for(
                session.call_tool("echo", {"message": "compass-smoke"}),
                timeout=15,
            )
            assert result.isError is False
            text = "\n".join(getattr(c, "text", "") for c in result.content)
            assert "compass-smoke" in text

            assert pool.stats()["live"] == 1
            await pool.evict("smoke", EVERYTHING_SERVER_NAME)
            assert pool.stats()["live"] == 0
        finally:
            await pool.stop()


# ── Manager: full enable → list_tools → call_tool flow ───────────────


class TestManagerEndToEnd:
    @pytest.mark.asyncio
    async def test_enable_lists_and_calls(self, real_manager, everything_in_catalog):
        mgr, _pool, _storage = real_manager
        # Enable: required_credentials is empty so {} is acceptable.
        row = await mgr.enable_connection(
            None,
            tenant_id="t1",
            server_name=EVERYTHING_SERVER_NAME,
            credentials={},
        )
        assert row["status"] == "enabled", row.get("error_message")

        # list_tools sees ≥10 namespaced tools.
        tools = await mgr.list_tools(None, tenant_id="t1")
        names = {t.qualified_name for t in tools}
        assert f"{EVERYTHING_SERVER_NAME}.echo" in names
        assert f"{EVERYTHING_SERVER_NAME}.get-sum" in names

        # call_tool round-trip.
        result = await mgr.call_tool(
            None,
            tenant_id="t1",
            qualified_name=f"{EVERYTHING_SERVER_NAME}.echo",
            arguments={"message": "compass-e2e"},
        )
        assert result.is_error is False
        assert "compass-e2e" in result.content
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_unknown_qualified_name_rejected(
        self, real_manager, everything_in_catalog
    ):
        from app.mcp.errors import MCPConnectionNotFoundError

        mgr, _pool, _storage = real_manager
        with pytest.raises(MCPConnectionNotFoundError):
            await mgr.call_tool(
                None,
                tenant_id="t1",
                qualified_name="not-a-server.nope",
                arguments={},
            )

    @pytest.mark.asyncio
    async def test_concurrent_first_callers_spawn_once_real_subprocess(
        self, real_manager, everything_in_catalog
    ):
        """The most important Phase-2 invariant: real subprocesses don't
        get duplicated under concurrent load. Spawn cost ~30s cold so a
        bug here would be very visible in prod."""
        mgr, pool, _storage = real_manager
        await mgr.enable_connection(
            None,
            tenant_id="t1",
            server_name=EVERYTHING_SERVER_NAME,
            credentials={},
        )
        # After enable, the health probe spawned + reaped via _fetch_tools.
        # The next set of concurrent calls should result in exactly one
        # live subprocess.
        async def call_once(i):
            return await mgr.call_tool(
                None,
                tenant_id="t1",
                qualified_name=f"{EVERYTHING_SERVER_NAME}.echo",
                arguments={"message": f"concur-{i}"},
            )

        results = await asyncio.gather(*[call_once(i) for i in range(5)])
        assert all(not r.is_error for r in results)
        assert pool.stats()["live"] == 1


# ── Token-gated: real Slack/GitHub/Notion (skipped without creds) ────


@pytest.mark.skipif(
    not os.environ.get("SLACK_BOT_TOKEN") or not os.environ.get("SLACK_TEAM_ID"),
    reason="SLACK_BOT_TOKEN and SLACK_TEAM_ID required",
)
class TestSlackWithRealCreds:
    """
    Runs only when SLACK_BOT_TOKEN + SLACK_TEAM_ID are exported. Hits
    Slack's API with whatever bot's token is provided. Read-only ops only —
    we list channels rather than post messages so a misconfigured bot
    can't pollute a workspace.
    """

    @pytest.mark.asyncio
    async def test_health_probe_passes(self, real_manager):
        mgr, _pool, _storage = real_manager
        row = await mgr.enable_connection(
            None,
            tenant_id="t1",
            server_name="slack",
            credentials={
                "SLACK_BOT_TOKEN": os.environ["SLACK_BOT_TOKEN"],
                "SLACK_TEAM_ID": os.environ["SLACK_TEAM_ID"],
            },
        )
        assert row["status"] == "enabled", row.get("error_message")
        tools = await mgr.list_tools(None, tenant_id="t1")
        names = {t.qualified_name for t in tools}
        # The deprecated server's tool surface — pinning this would be
        # brittle, so just check we got something Slack-shaped.
        assert any(n.startswith("slack.") for n in names)


@pytest.mark.skipif(
    not os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"),
    reason="GITHUB_PERSONAL_ACCESS_TOKEN required",
)
class TestGitHubWithRealCreds:
    @pytest.mark.asyncio
    async def test_health_probe_passes(self, real_manager):
        mgr, _pool, _storage = real_manager
        row = await mgr.enable_connection(
            None,
            tenant_id="t1",
            server_name="github",
            credentials={
                "GITHUB_PERSONAL_ACCESS_TOKEN": os.environ[
                    "GITHUB_PERSONAL_ACCESS_TOKEN"
                ],
            },
        )
        assert row["status"] == "enabled", row.get("error_message")


@pytest.mark.skipif(
    not os.environ.get("NOTION_API_KEY"),
    reason="NOTION_API_KEY required",
)
class TestNotionWithRealCreds:
    @pytest.mark.asyncio
    async def test_health_probe_passes(self, real_manager):
        mgr, _pool, _storage = real_manager
        row = await mgr.enable_connection(
            None,
            tenant_id="t1",
            server_name="notion",
            credentials={"NOTION_API_KEY": os.environ["NOTION_API_KEY"]},
        )
        assert row["status"] == "enabled", row.get("error_message")
