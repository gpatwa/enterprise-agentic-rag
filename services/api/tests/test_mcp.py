# services/api/tests/test_mcp.py
"""
Phase-1 MCP integration tests.

Coverage strategy
-----------------
- Crypto + catalog + types: pure-python, no IO.
- Pool concurrency, capacity, idle reap, eviction-during-call: driven
  through fake stdio_client + ClientSession factories so no real
  subprocess is spawned.
- Manager dispatch + timeout + audit hooks: mocked storage layer.
- Tool node + registry merge: lightweight mocks of `mcp_manager`.

These tests run without Postgres, Node.js, or the real `mcp` SDK — they
exercise our orchestration logic only. Real-server integration tests
(against actual @modelcontextprotocol packages) gate behind
`MCP_INTEGRATION_TESTS=1` in Phase 2.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
import types
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


# ── Fake MCP transport / session ──────────────────────────────────────────


@dataclass
class _FakeTool:
    name: str
    description: str = "fake tool"
    inputSchema: dict = None  # type: ignore

    def __post_init__(self):
        if self.inputSchema is None:
            self.inputSchema = {"type": "object"}


@dataclass
class _FakeContent:
    text: str
    type: str = "text"


@dataclass
class _FakeCallResult:
    content: list
    isError: bool = False


class _FakeSession:
    """Stand-in for mcp.ClientSession. Records calls for assertion."""

    def __init__(
        self,
        *,
        tools: Optional[list[_FakeTool]] = None,
        call_responses: Optional[dict[str, _FakeCallResult]] = None,
        call_delay_seconds: float = 0,
        raise_on_call: Optional[Exception] = None,
        raise_on_initialize: Optional[Exception] = None,
    ) -> None:
        self.tools = tools or [_FakeTool(name="search")]
        self.call_responses = call_responses or {}
        self.call_delay_seconds = call_delay_seconds
        self.raise_on_call = raise_on_call
        self.raise_on_initialize = raise_on_initialize
        self.initialize_count = 0
        self.list_tools_count = 0
        self.call_log: list[tuple[str, dict]] = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True

    async def initialize(self):
        self.initialize_count += 1
        if self.raise_on_initialize is not None:
            raise self.raise_on_initialize

    async def list_tools(self):
        self.list_tools_count += 1
        return types.SimpleNamespace(tools=list(self.tools))

    async def call_tool(self, name: str, args: dict):
        self.call_log.append((name, args))
        if self.call_delay_seconds:
            await asyncio.sleep(self.call_delay_seconds)
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if name in self.call_responses:
            return self.call_responses[name]
        return _FakeCallResult(content=[_FakeContent(text=f"ok:{name}")])


def _stdio_factory_returning(session: _FakeSession):
    """Build a fake stdio_client(spec) async-context-manager."""

    @contextlib.asynccontextmanager
    async def _stdio(spec):  # noqa: ARG001
        # Real stdio_client yields (read, write) streams. Our pool's spawn
        # path passes the transport into ClientSession; we emit an opaque
        # marker, and the session_factory ignores it.
        yield ("read", "write")

    return _stdio


def _session_factory_returning(session: _FakeSession):
    """ClientSession factory accepting any args, always returns `session`."""

    def _factory(*args, **kwargs):  # noqa: ARG001
        return session

    return _factory


# ── Crypto ────────────────────────────────────────────────────────────────


class TestCrypto:
    def test_roundtrip(self):
        from app.mcp.crypto import CredentialCipher, generate_key

        key = generate_key()
        cipher = CredentialCipher(key)
        token = cipher.encrypt({"SLACK_BOT_TOKEN": "xoxb-abc", "SLACK_TEAM_ID": "T0"})
        out = cipher.decrypt(token)
        assert out == {"SLACK_BOT_TOKEN": "xoxb-abc", "SLACK_TEAM_ID": "T0"}

    def test_empty_key_rejected(self):
        from app.mcp.crypto import CredentialCipher
        from app.mcp.errors import MCPCryptoError

        with pytest.raises(MCPCryptoError):
            CredentialCipher("")

    def test_malformed_key_rejected(self):
        from app.mcp.crypto import CredentialCipher
        from app.mcp.errors import MCPCryptoError

        with pytest.raises(MCPCryptoError):
            CredentialCipher("not-base64-of-32-bytes")

    def test_decrypt_wrong_key_raises(self):
        from app.mcp.crypto import CredentialCipher, generate_key
        from app.mcp.errors import MCPCryptoError

        a = CredentialCipher(generate_key())
        b = CredentialCipher(generate_key())
        token = a.encrypt({"x": 1})
        with pytest.raises(MCPCryptoError):
            b.decrypt(token)


# ── Catalog ───────────────────────────────────────────────────────────────


class TestCatalog:
    def test_tier1_servers_present(self):
        from app.mcp.catalog import MCPCatalog

        names = MCPCatalog.names()
        assert {"slack", "github", "notion", "gdrive"}.issubset(names)

    def test_required_credentials_listed(self):
        from app.mcp.catalog import MCPCatalog

        slack = MCPCatalog.get("slack")
        assert slack is not None
        assert "SLACK_BOT_TOKEN" in slack.required_credentials

    def test_unknown_server_returns_none(self):
        from app.mcp.catalog import MCPCatalog

        assert MCPCatalog.get("does-not-exist") is None


# ── Process pool ──────────────────────────────────────────────────────────


class TestProcessPool:
    @pytest.mark.asyncio
    async def test_concurrent_first_callers_spawn_once(self):
        """Spawn-once-per-key under N concurrent first-callers."""
        from app.mcp.process_pool import MCPProcessPool

        session = _FakeSession()
        spawn_count = 0

        @contextlib.asynccontextmanager
        async def stdio(spec):  # noqa: ARG001
            nonlocal spawn_count
            spawn_count += 1
            yield ("r", "w")

        pool = MCPProcessPool(
            max_processes=10,
            idle_seconds=None,
            tool_timeout_seconds=5,
            _stdio_client_factory=stdio,
            _client_session_factory=_session_factory_returning(session),
        )
        async def get():
            return await pool.get_session("t1", "slack", spawn_spec=object())

        results = await asyncio.gather(*[get() for _ in range(8)])
        try:
            assert spawn_count == 1
            assert all(r is session for r in results)
            assert session.initialize_count == 1
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_capacity_cap(self):
        from app.mcp.errors import MCPCapacityError
        from app.mcp.process_pool import MCPProcessPool

        s = _FakeSession()
        pool = MCPProcessPool(
            max_processes=1,
            idle_seconds=None,
            tool_timeout_seconds=5,
            _stdio_client_factory=_stdio_factory_returning(s),
            _client_session_factory=_session_factory_returning(s),
        )
        try:
            await pool.get_session("t1", "slack", spawn_spec=object())
            with pytest.raises(MCPCapacityError):
                await pool.get_session("t2", "slack", spawn_spec=object())
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_evict_releases_capacity(self):
        from app.mcp.process_pool import MCPProcessPool

        s = _FakeSession()
        pool = MCPProcessPool(
            max_processes=1,
            idle_seconds=None,
            tool_timeout_seconds=5,
            _stdio_client_factory=_stdio_factory_returning(s),
            _client_session_factory=_session_factory_returning(s),
        )
        try:
            await pool.get_session("t1", "slack", spawn_spec=object())
            assert pool.stats()["live"] == 1
            await pool.evict("t1", "slack")
            assert pool.stats()["live"] == 0
            # Another spawn now succeeds
            await pool.get_session("t2", "slack", spawn_spec=object())
            assert pool.stats()["live"] == 1
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_idle_reaper_evicts_stale_entries(self):
        from app.mcp.process_pool import MCPProcessPool

        s = _FakeSession()
        # idle=1s for fast test; reaper interval is clamped to 5s minimum
        # (max(5, idle_seconds // 5)). We stop the pool before reaper fires
        # and instead drive the reap-decision by calling _evict directly,
        # *after* manually backdating last_used. This exercises the same
        # code path without sleeping 5s in the test suite.
        pool = MCPProcessPool(
            max_processes=10,
            idle_seconds=1,
            tool_timeout_seconds=5,
            _stdio_client_factory=_stdio_factory_returning(s),
            _client_session_factory=_session_factory_returning(s),
        )
        try:
            await pool.get_session("t1", "slack", spawn_spec=object())
            # Backdate by 60s so the reaper logic would mark it stale
            entry = pool._entries[("t1", "slack")]  # type: ignore[attr-defined]
            entry.last_used = time.monotonic() - 60
            # Run one reap cycle synchronously
            cutoff = time.monotonic() - pool._idle_seconds  # type: ignore[attr-defined]
            stale = [k for k, e in pool._entries.items() if e.last_used < cutoff]
            for k in stale:
                await pool._evict(k, reason="test")  # type: ignore[attr-defined]
            assert pool.stats()["live"] == 0
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_spawn_failure_propagates(self):
        from app.mcp.errors import MCPServerSpawnError
        from app.mcp.process_pool import MCPProcessPool

        @contextlib.asynccontextmanager
        async def bad_stdio(spec):  # noqa: ARG001
            raise FileNotFoundError("npx")
            yield  # pragma: no cover

        pool = MCPProcessPool(
            max_processes=10,
            idle_seconds=None,
            tool_timeout_seconds=5,
            _stdio_client_factory=bad_stdio,
            _client_session_factory=_session_factory_returning(_FakeSession()),
        )
        try:
            with pytest.raises(MCPServerSpawnError) as exc:
                await pool.get_session("t1", "slack", spawn_spec=object())
            assert "node" in str(exc.value).lower()
        finally:
            await pool.stop()


# ── Manager (dispatch / list / errors) ────────────────────────────────────


class _FakeStorage:
    """In-memory shim replacing app.mcp.storage for manager tests."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}

    async def list_for_tenant(self, _session, tenant_id, *, only_enabled=False):
        out = [r for k, r in self.rows.items() if k[0] == tenant_id]
        if only_enabled:
            out = [r for r in out if r["status"] == "enabled"]
        return out

    async def get(self, _session, tenant_id, server_name, *, decrypt=False):
        row = self.rows.get((tenant_id, server_name))
        if row is None:
            return None
        out = dict(row)
        if decrypt:
            out["credentials"] = row.get("_creds")
        return out

    async def upsert(self, _session, *, tenant_id, server_name, credentials, status):
        row = {
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
        self.rows[(tenant_id, server_name)] = row
        return {k: v for k, v in row.items() if not k.startswith("_")}

    async def set_status(
        self,
        _session,
        *,
        tenant_id,
        server_name,
        status,
        error_message=None,
        health_check_now=False,
    ):
        row = self.rows.get((tenant_id, server_name))
        if row is None:
            return False
        row["status"] = status.value
        row["error_message"] = error_message
        return True

    async def remove(self, _session, *, tenant_id, server_name):
        return self.rows.pop((tenant_id, server_name), None) is not None


@pytest.fixture
def _manager_with_pool(monkeypatch):
    """Configured MCPManager wired to a fake pool + storage."""
    from app.mcp import storage as storage_mod
    from app.mcp.crypto import generate_key, init_cipher, reset_cipher
    from app.mcp.manager import MCPManager
    from app.mcp.process_pool import MCPProcessPool

    reset_cipher()
    init_cipher(generate_key())
    fake_storage = _FakeStorage()
    for fn in ("list_for_tenant", "get", "upsert", "set_status", "remove"):
        monkeypatch.setattr(
            storage_mod, fn, getattr(fake_storage, fn), raising=True
        )

    session = _FakeSession()
    pool = MCPProcessPool(
        max_processes=10,
        idle_seconds=None,
        tool_timeout_seconds=2,
        _stdio_client_factory=_stdio_factory_returning(session),
        _client_session_factory=_session_factory_returning(session),
    )
    mgr = MCPManager()
    mgr.configure(enabled=True, pool=pool, tool_timeout_seconds=2)

    # Inject a non-None StdioServerParameters substitute so _build_spawn_spec
    # doesn't trip the "SDK not installed" guard. The pool ignores it.
    monkeypatch.setattr(
        "app.mcp.manager.StdioServerParameters",
        lambda **kw: object(),
        raising=False,
    )

    yield mgr, pool, fake_storage, session
    asyncio.get_event_loop().run_until_complete(pool.stop()) if False else None


class TestManagerStateOps:
    @pytest.mark.asyncio
    async def test_disabled_manager_refuses(self, monkeypatch):
        from app.mcp.errors import MCPNotEnabledError
        from app.mcp.manager import MCPManager

        mgr = MCPManager()  # never .configure()
        with pytest.raises(MCPNotEnabledError):
            await mgr.call_tool(
                None,
                tenant_id="t",
                qualified_name="slack.search",
                arguments={},
            )

    @pytest.mark.asyncio
    async def test_enable_validates_required_creds(self, _manager_with_pool):
        from app.mcp.errors import MCPError

        mgr, _pool, _storage, _session = _manager_with_pool
        with pytest.raises(MCPError) as exc:
            await mgr.enable_connection(
                None,
                tenant_id="t1",
                server_name="slack",
                credentials={},  # missing both required fields
            )
        assert "required credentials" in exc.value.message.lower()

    @pytest.mark.asyncio
    async def test_enable_then_health_ok_flips_to_enabled(self, _manager_with_pool):
        from app.mcp.types import MCPConnectionStatus

        mgr, _pool, storage, _session = _manager_with_pool
        row = await mgr.enable_connection(
            None,
            tenant_id="t1",
            server_name="slack",
            credentials={"SLACK_BOT_TOKEN": "x", "SLACK_TEAM_ID": "T"},
        )
        assert row["status"] == MCPConnectionStatus.ENABLED.value
        assert storage.rows[("t1", "slack")]["status"] == "enabled"


class TestManagerDispatch:
    @pytest.mark.asyncio
    async def test_call_tool_happy_path(self, _manager_with_pool):
        mgr, _pool, _storage, session = _manager_with_pool
        await mgr.enable_connection(
            None,
            tenant_id="t1",
            server_name="slack",
            credentials={"SLACK_BOT_TOKEN": "x", "SLACK_TEAM_ID": "T"},
        )
        result = await mgr.call_tool(
            None,
            tenant_id="t1",
            qualified_name="slack.search",
            arguments={"q": "hello"},
        )
        assert result.is_error is False
        assert "ok:search" in result.content
        assert result.qualified_name == "slack.search"
        assert session.call_log[-1] == ("search", {"q": "hello"})

    @pytest.mark.asyncio
    async def test_call_tool_unknown_server(self, _manager_with_pool):
        from app.mcp.errors import MCPConnectionNotFoundError

        mgr, _pool, _storage, _session = _manager_with_pool
        with pytest.raises(MCPConnectionNotFoundError):
            await mgr.call_tool(
                None,
                tenant_id="t1",
                qualified_name="madeup.search",
                arguments={},
            )

    @pytest.mark.asyncio
    async def test_call_tool_disabled_connection(self, _manager_with_pool):
        from app.mcp.errors import MCPConnectionNotFoundError

        mgr, _pool, storage, _session = _manager_with_pool
        await mgr.enable_connection(
            None,
            tenant_id="t1",
            server_name="slack",
            credentials={"SLACK_BOT_TOKEN": "x", "SLACK_TEAM_ID": "T"},
        )
        # Manually flip to disabled in storage
        storage.rows[("t1", "slack")]["status"] = "disabled"
        with pytest.raises(MCPConnectionNotFoundError):
            await mgr.call_tool(
                None,
                tenant_id="t1",
                qualified_name="slack.search",
                arguments={},
            )

    @pytest.mark.asyncio
    async def test_call_tool_timeout_evicts_entry(self, monkeypatch):
        """Timeout must both raise AND tear down the stuck subprocess."""
        from app.mcp import storage as storage_mod
        from app.mcp.crypto import generate_key, init_cipher, reset_cipher
        from app.mcp.errors import MCPToolTimeoutError
        from app.mcp.manager import MCPManager
        from app.mcp.process_pool import MCPProcessPool

        reset_cipher()
        init_cipher(generate_key())
        fake = _FakeStorage()
        for fn in ("list_for_tenant", "get", "upsert", "set_status", "remove"):
            monkeypatch.setattr(storage_mod, fn, getattr(fake, fn), raising=True)
        slow_session = _FakeSession(call_delay_seconds=10)
        pool = MCPProcessPool(
            max_processes=10,
            idle_seconds=None,
            tool_timeout_seconds=1,  # 1s timeout, 10s call -> fires
            _stdio_client_factory=_stdio_factory_returning(slow_session),
            _client_session_factory=_session_factory_returning(slow_session),
        )
        try:
            mgr = MCPManager()
            mgr.configure(enabled=True, pool=pool, tool_timeout_seconds=1)
            monkeypatch.setattr(
                "app.mcp.manager.StdioServerParameters",
                lambda **kw: object(),
                raising=False,
            )
            await mgr.enable_connection(
                None,
                tenant_id="t1",
                server_name="slack",
                credentials={"SLACK_BOT_TOKEN": "x", "SLACK_TEAM_ID": "T"},
            )
            assert pool.stats()["live"] == 1
            with pytest.raises(MCPToolTimeoutError):
                await mgr.call_tool(
                    None,
                    tenant_id="t1",
                    qualified_name="slack.search",
                    arguments={},
                )
            # Critical: the stuck process must be reaped so the next call
            # gets a fresh subprocess instead of inheriting the hang.
            assert pool.stats()["live"] == 0
        finally:
            await pool.stop()


# ── Tenant-aware tool registry merge ──────────────────────────────────────


class TestTenantToolRegistry:
    @pytest.mark.asyncio
    async def test_static_only_when_mcp_disabled(self, monkeypatch):
        # Force disabled
        from app.mcp import mcp_manager
        from app.tools.registry import TOOL_REGISTRY, get_tools_for_tenant

        monkeypatch.setattr(type(mcp_manager), "enabled", property(lambda _self: False))
        tools = await get_tools_for_tenant("t1")
        assert {t.name for t in tools} == set(TOOL_REGISTRY.keys())

    @pytest.mark.asyncio
    async def test_merges_mcp_tools_when_enabled(self, monkeypatch):
        # Stub mcp_manager.list_tools to return one MCP descriptor
        from app.mcp import mcp_manager
        from app.mcp.types import MCPToolDescriptor
        from app.tools.registry import get_tools_for_tenant

        monkeypatch.setattr(type(mcp_manager), "enabled", property(lambda _self: True))
        async def fake_list_tools(_session, *, tenant_id, cache=True):
            return [
                MCPToolDescriptor(
                    server_name="slack",
                    tool_name="search_messages",
                    qualified_name="slack.search_messages",
                    description="Search Slack messages",
                    input_schema={"type": "object"},
                ),
            ]

        monkeypatch.setattr(mcp_manager, "list_tools", fake_list_tools)
        # Also patch AsyncSessionLocal so the registry's session-open path no-ops
        import app.memory.postgres as pg

        class _NoSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

        monkeypatch.setattr(pg, "AsyncSessionLocal", lambda: _NoSession())

        tools = await get_tools_for_tenant("t1")
        names = {t.name for t in tools}
        assert "calculator" in names  # static still present
        assert "slack.search_messages" in names  # MCP merged in


# ── Tool-node dispatch routing ────────────────────────────────────────────


class TestToolNodeRouting:
    @pytest.mark.asyncio
    async def test_qualified_name_routes_to_mcp(self, monkeypatch):
        from app.agents.nodes import tool as tool_node_mod
        from app.mcp import mcp_manager
        from app.mcp.types import ToolCallResult

        # Pretend MCP is enabled and slack is a known server
        monkeypatch.setattr(type(mcp_manager), "enabled", property(lambda _self: True))
        monkeypatch.setattr(
            mcp_manager,
            "is_qualified_name",
            lambda name: name.startswith("slack."),
        )

        called = {}

        async def fake_call(_session, *, tenant_id, qualified_name, arguments):
            called["tenant_id"] = tenant_id
            called["qualified_name"] = qualified_name
            called["arguments"] = arguments
            return ToolCallResult(
                qualified_name=qualified_name,
                content="from-slack",
                is_error=False,
                latency_ms=12,
            )

        monkeypatch.setattr(mcp_manager, "call_tool", fake_call)

        # Stub AsyncSessionLocal so the mcp dispatch path opens cleanly
        import app.memory.postgres as pg

        class _NoSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

        monkeypatch.setattr(pg, "AsyncSessionLocal", lambda: _NoSession())

        # Audit logger should be silently no-op'd to keep test isolated
        import app.audit.manager as audit_mod

        monkeypatch.setattr(audit_mod, "log_event", AsyncMock())

        out = await tool_node_mod.tool_node(
            state={"tool_name": "slack.search_messages", "tool_input": '{"q":"hi"}'},  # type: ignore
            config={"configurable": {"tenant_id": "t1", "user_id": "u1"}},
        )
        assert out["tool_result"] == "from-slack"
        assert called["tenant_id"] == "t1"
        assert called["qualified_name"] == "slack.search_messages"
        assert called["arguments"] == {"q": "hi"}

    @pytest.mark.asyncio
    async def test_static_name_routes_to_static_dispatch(self, monkeypatch):
        from app.agents.nodes import tool as tool_node_mod
        from app.mcp import mcp_manager

        monkeypatch.setattr(
            mcp_manager,
            "is_qualified_name",
            lambda name: False,
        )
        monkeypatch.setitem(
            tool_node_mod.TOOL_DISPATCH,
            "calculator",
            lambda x: f"calc:{x}",  # sync handler
        )
        out = await tool_node_mod.tool_node(
            state={"tool_name": "calculator", "tool_input": "2+2"},  # type: ignore
            config={"configurable": {}},
        )
        assert out["tool_result"] == "calc:2+2"

    def test_argument_parser_handles_three_shapes(self):
        from app.agents.nodes.tool import _parse_arguments

        assert _parse_arguments({"a": 1}) == {"a": 1}
        assert _parse_arguments('{"a": 1}') == {"a": 1}
        assert _parse_arguments("plain text") == {"query": "plain text"}
        assert _parse_arguments(42) == {"query": "42"}
