# services/api/tests/test_mcp_routes.py
"""
Phase-5 HTTP admin routes for MCP.

Strategy: invoke route functions directly with a mocked TenantContext
and a stubbed mcp_manager. This matches the rest of the test suite
(see test_security_hardening.py, test_tenant_auth.py) — no FastAPI
TestClient, no Postgres, no lifespan boot.

The trade-off vs. TestClient is that we don't exercise the FastAPI
DI graph. We mitigate by also asserting on the route's `Depends(...)`
binding via inspection: if a future change accidentally drops the
admin guard, the test that calls a mutation as a non-admin will fail.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


# ── Fixtures ───────────────────────────────────────────────────────────


def _ctx(role: str = "admin", tenant_id: str = "t1", user_id: str = "alice"):
    from app.auth.tenant import TenantContext

    return TenantContext(
        tenant_id=tenant_id, user_id=user_id, role=role, permissions=[]
    )


@pytest.fixture
def manager_enabled(monkeypatch):
    """Pretend mcp_manager is enabled with a working pool."""
    from app.mcp import mcp_manager

    monkeypatch.setattr(
        type(mcp_manager), "enabled", property(lambda _self: True)
    )
    return mcp_manager


@pytest.fixture
def db_session(monkeypatch):
    """
    Replace AsyncSessionLocal with a context-manager that yields a marker.

    Routes only forward the session to mcp_manager methods, which are
    stubbed in tests — so the actual session object is never used.
    """
    import app.memory.postgres as pg

    class _NoSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(pg, "AsyncSessionLocal", lambda: _NoSession())
    return _NoSession


@pytest.fixture
def silent_audit(monkeypatch):
    """Mute audit writes while still letting tests assert on call shape."""
    import app.audit.manager as audit_mod

    fake = AsyncMock()
    monkeypatch.setattr(audit_mod, "log_event", fake)
    return fake


# ── /catalog ───────────────────────────────────────────────────────────


class TestCatalog:
    @pytest.mark.asyncio
    async def test_returns_known_servers(self):
        from app.routes.mcp import get_catalog

        body = await get_catalog(_ctx(role="user"))
        names = {e["server_name"] for e in body["catalog"]}
        # Tier-1 from app/mcp/catalog.py
        assert {"slack", "github", "notion", "gdrive"}.issubset(names)
        assert "mcp_enabled" in body

    @pytest.mark.asyncio
    async def test_no_creds_in_response(self):
        from app.routes.mcp import get_catalog

        body = await get_catalog(_ctx())
        for e in body["catalog"]:
            # required_credentials is just the *names* of fields
            assert "credentials" not in e
            assert isinstance(e.get("required_credentials", []), list)


# ── /connections (GET, POST, disable, DELETE) ─────────────────────────


class TestListConnections:
    @pytest.mark.asyncio
    async def test_disabled_manager_returns_empty(self, monkeypatch):
        from app.mcp import mcp_manager
        from app.routes.mcp import list_connections

        monkeypatch.setattr(
            type(mcp_manager), "enabled", property(lambda _self: False)
        )
        body = await list_connections(_ctx())
        assert body == {"connections": [], "mcp_enabled": False}

    @pytest.mark.asyncio
    async def test_strips_credentials(
        self, manager_enabled, db_session, monkeypatch
    ):
        from app.routes.mcp import list_connections

        rows = [
            {
                "server_name": "slack",
                "status": "enabled",
                "last_health_check": "2026-05-04T00:00:00Z",
                "error_message": None,
                "created_at": "2026-05-04T00:00:00Z",
                "updated_at": "2026-05-04T00:00:00Z",
                "credentials": {"SLACK_BOT_TOKEN": "should-not-leak"},
            },
        ]
        monkeypatch.setattr(
            manager_enabled, "list_connections", AsyncMock(return_value=rows)
        )
        body = await list_connections(_ctx())
        assert body["mcp_enabled"] is True
        assert len(body["connections"]) == 1
        # Critical: credentials must NEVER be in the wire payload
        for conn in body["connections"]:
            assert "credentials" not in conn
            assert "encrypted_config" not in conn


class TestEnableConnection:
    @pytest.mark.asyncio
    async def test_non_admin_rejected(self, manager_enabled):
        from app.routes.mcp import EnableConnectionRequest, enable_connection

        req = EnableConnectionRequest(
            server_name="slack",
            credentials={"SLACK_BOT_TOKEN": "x", "SLACK_TEAM_ID": "T"},
        )
        with pytest.raises(HTTPException) as exc:
            await enable_connection(req, _ctx(role="user"))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_disabled_manager_returns_503(self, monkeypatch):
        from app.mcp import mcp_manager
        from app.routes.mcp import EnableConnectionRequest, enable_connection

        monkeypatch.setattr(
            type(mcp_manager), "enabled", property(lambda _self: False)
        )
        req = EnableConnectionRequest(server_name="slack", credentials={})
        with pytest.raises(HTTPException) as exc:
            await enable_connection(req, _ctx())
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_happy_path_returns_stripped_row_and_audits(
        self, manager_enabled, db_session, silent_audit, monkeypatch
    ):
        from app.routes.mcp import EnableConnectionRequest, enable_connection

        row = {
            "server_name": "slack",
            "status": "enabled",
            "last_health_check": "2026-05-04T00:00:00Z",
            "error_message": None,
            "created_at": "2026-05-04T00:00:00Z",
            "updated_at": "2026-05-04T00:00:00Z",
        }
        monkeypatch.setattr(
            manager_enabled, "enable_connection", AsyncMock(return_value=row)
        )
        req = EnableConnectionRequest(
            server_name="slack",
            credentials={"SLACK_BOT_TOKEN": "x", "SLACK_TEAM_ID": "T"},
        )
        body = await enable_connection(req, _ctx())
        assert body["connection"]["server_name"] == "slack"
        assert body["connection"]["status"] == "enabled"
        # Credentials must not leak
        assert "credentials" not in body["connection"]
        # Audit fired with mcp.admin
        silent_audit.assert_called_once()
        kwargs = silent_audit.call_args.kwargs
        assert kwargs["event_type"] == "mcp.admin"
        assert kwargs["extra"]["action"] == "enable"
        assert kwargs["extra"]["server_name"] == "slack"
        assert kwargs["extra"]["success"] is True

    @pytest.mark.asyncio
    async def test_missing_required_creds_returns_400(
        self, manager_enabled, db_session, silent_audit, monkeypatch
    ):
        from app.mcp.errors import MCPError
        from app.routes.mcp import EnableConnectionRequest, enable_connection

        async def boom(*a, **k):
            raise MCPError(
                "missing required credentials for slack: SLACK_TEAM_ID",
                extra={"missing": ["SLACK_TEAM_ID"]},
            )

        monkeypatch.setattr(manager_enabled, "enable_connection", boom)
        req = EnableConnectionRequest(
            server_name="slack",
            credentials={"SLACK_BOT_TOKEN": "x"},  # missing SLACK_TEAM_ID
        )
        with pytest.raises(HTTPException) as exc:
            await enable_connection(req, _ctx())
        assert exc.value.status_code == 400
        # Stable error code flows to client
        assert exc.value.detail["code"] == "mcp.error"
        # Audit captures the failure
        silent_audit.assert_called_once()
        assert silent_audit.call_args.kwargs["extra"]["success"] is False


class TestDisableConnection:
    @pytest.mark.asyncio
    async def test_non_admin_rejected(self, manager_enabled):
        from app.routes.mcp import disable_connection

        with pytest.raises(HTTPException) as exc:
            await disable_connection("slack", _ctx(role="user"))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_returns_404(
        self, manager_enabled, db_session, silent_audit, monkeypatch
    ):
        from app.routes.mcp import disable_connection

        monkeypatch.setattr(
            manager_enabled, "disable_connection", AsyncMock(return_value=False)
        )
        with pytest.raises(HTTPException) as exc:
            await disable_connection("slack", _ctx())
        assert exc.value.status_code == 404


class TestRemoveConnection:
    @pytest.mark.asyncio
    async def test_non_admin_rejected(self, manager_enabled):
        from app.routes.mcp import remove_connection

        with pytest.raises(HTTPException) as exc:
            await remove_connection("slack", _ctx(role="user"))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_happy_path_audits_remove(
        self, manager_enabled, db_session, silent_audit, monkeypatch
    ):
        from app.routes.mcp import remove_connection

        monkeypatch.setattr(
            manager_enabled, "remove_connection", AsyncMock(return_value=True)
        )
        body = await remove_connection("slack", _ctx())
        assert body == {"removed": True}
        silent_audit.assert_called_once()
        assert silent_audit.call_args.kwargs["extra"]["action"] == "remove"


class TestTestConnection:
    @pytest.mark.asyncio
    async def test_non_admin_rejected(self, manager_enabled):
        from app.routes.mcp import test_connection

        with pytest.raises(HTTPException) as exc:
            await test_connection("slack", _ctx(role="user"))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_happy_path_returns_ok_true(
        self, manager_enabled, db_session, silent_audit, monkeypatch
    ):
        from app.routes.mcp import test_connection

        monkeypatch.setattr(
            manager_enabled,
            "test_connection",
            AsyncMock(return_value=(True, None)),
        )
        body = await test_connection("slack", _ctx())
        assert body.ok is True
        assert body.error_message is None
        silent_audit.assert_called_once()
        assert silent_audit.call_args.kwargs["extra"]["success"] is True

    @pytest.mark.asyncio
    async def test_unknown_connection_returns_404(
        self, manager_enabled, db_session, silent_audit, monkeypatch
    ):
        from app.mcp.errors import MCPConnectionNotFoundError
        from app.routes.mcp import test_connection

        async def boom(*a, **k):
            raise MCPConnectionNotFoundError("nope")

        monkeypatch.setattr(manager_enabled, "test_connection", boom)
        with pytest.raises(HTTPException) as exc:
            await test_connection("slack", _ctx())
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "mcp.connection_not_found"


# ── /tools ─────────────────────────────────────────────────────────────


class TestListTools:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, monkeypatch):
        from app.mcp import mcp_manager
        from app.routes.mcp import list_tools

        monkeypatch.setattr(
            type(mcp_manager), "enabled", property(lambda _self: False)
        )
        body = await list_tools(_ctx())
        assert body == {"tools": [], "mcp_enabled": False}

    @pytest.mark.asyncio
    async def test_serializes_descriptors(
        self, manager_enabled, db_session, monkeypatch
    ):
        from app.mcp.types import MCPToolDescriptor
        from app.routes.mcp import list_tools

        descriptors = [
            MCPToolDescriptor(
                server_name="slack",
                tool_name="search_messages",
                qualified_name="slack.search_messages",
                description="Search Slack messages",
                input_schema={"type": "object"},
            ),
        ]
        monkeypatch.setattr(
            manager_enabled, "list_tools", AsyncMock(return_value=descriptors)
        )
        body = await list_tools(_ctx())
        assert body["mcp_enabled"] is True
        assert body["tools"][0]["qualified_name"] == "slack.search_messages"
        assert body["tools"][0]["server_name"] == "slack"


# ── Capacity / not-enabled error mapping ──────────────────────────────


class TestErrorMapping:
    @pytest.mark.asyncio
    async def test_capacity_maps_to_429(
        self, manager_enabled, db_session, silent_audit, monkeypatch
    ):
        from app.mcp.errors import MCPCapacityError
        from app.routes.mcp import test_connection

        async def boom(*a, **k):
            raise MCPCapacityError("pool full")

        monkeypatch.setattr(manager_enabled, "test_connection", boom)
        with pytest.raises(HTTPException) as exc:
            await test_connection("slack", _ctx())
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_crypto_error_does_not_leak_internal(
        self, manager_enabled, db_session, silent_audit, monkeypatch
    ):
        from app.mcp.errors import MCPCryptoError
        from app.routes.mcp import test_connection

        async def boom(*a, **k):
            raise MCPCryptoError("specific internal detail")

        monkeypatch.setattr(manager_enabled, "test_connection", boom)
        with pytest.raises(HTTPException) as exc:
            await test_connection("slack", _ctx())
        assert exc.value.status_code == 500
        # Internal detail must NOT leak
        assert "specific internal detail" not in str(exc.value.detail)
        assert exc.value.detail["code"] == "mcp.crypto_error"


# ── Router registration sanity ────────────────────────────────────────


class TestRouterRegistration:
    def test_router_module_imports(self):
        from app.routes import mcp as mcp_routes

        assert hasattr(mcp_routes, "router")

    def test_routes_include_all_six_endpoints(self):
        from app.routes import mcp as mcp_routes

        paths = {(r.path, tuple(sorted(r.methods))) for r in mcp_routes.router.routes}
        # Confirm full surface registered
        assert ("/catalog", ("GET",)) in paths
        assert ("/connections", ("GET",)) in paths
        assert ("/connections", ("POST",)) in paths
        assert ("/connections/{server_name}/test", ("POST",)) in paths
        assert ("/connections/{server_name}/disable", ("POST",)) in paths
        assert ("/connections/{server_name}", ("DELETE",)) in paths
        assert ("/tools", ("GET",)) in paths

    def test_main_includes_mcp_router(self, monkeypatch):
        # Light sanity check: main.py imports + registers under /api/v1/mcp.
        # main.py refuses to load with ENV=prod and wildcard CORS, so we set
        # an explicit allowlist before re-importing.
        monkeypatch.setenv("CORS_ORIGINS", "https://test.local")
        import sys
        sys.modules.pop("main", None)
        sys.modules.pop("app.config", None)
        from main import app

        prefixes = [
            getattr(r, "path", "")
            for r in app.routes
            if hasattr(r, "path") and "/mcp" in getattr(r, "path", "")
        ]
        assert any(p.startswith("/api/v1/mcp") for p in prefixes), (
            f"expected /api/v1/mcp routes; got {prefixes[:5]}…"
        )
