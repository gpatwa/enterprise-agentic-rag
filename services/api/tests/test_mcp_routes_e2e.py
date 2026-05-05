# services/api/tests/test_mcp_routes_e2e.py
"""
End-to-end smoke tests for the MCP HTTP surface.

Why this file in addition to test_mcp_routes.py
-----------------------------------------------
`test_mcp_routes.py` calls route functions directly. That gives us
fast, deterministic logic coverage but bypasses everything FastAPI
adds on top of the python function:

    - Depends() resolution (the get_tenant_context chain)
    - Pydantic request-body parsing and validation
    - response_model serialization (and the strip-credentials guarantee)
    - Real HTTP status codes mapping from HTTPException
    - URL path matching and method routing

This file boots a minimal FastAPI app with ONLY the MCP router mounted,
overrides the auth dependency, mocks the manager + storage at the same
level the unit tests do, and drives real HTTP requests via TestClient.
A failure here proves FastAPI integration drift; the unit tests stay as
the fast logic-coverage layer.
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


# ── App + dependency-override fixtures ───────────────────────────────


def _make_app() -> FastAPI:
    """Minimal FastAPI app with only the MCP router mounted."""
    from app.routes import mcp as mcp_routes

    app = FastAPI()
    app.include_router(mcp_routes.router, prefix="/api/v1/mcp")
    return app


def _admin_context():
    from app.auth.tenant import TenantContext

    return TenantContext(
        tenant_id="t1", user_id="alice", role="admin", permissions=["read", "write"]
    )


def _user_context():
    from app.auth.tenant import TenantContext

    return TenantContext(
        tenant_id="t1", user_id="bob", role="user", permissions=["read"]
    )


@pytest.fixture
def admin_client(monkeypatch):
    """TestClient with TenantContext = admin and a manager+storage stub."""
    from app.auth.tenant import get_tenant_context
    from app.mcp import mcp_manager
    import app.memory.postgres as pg

    # Manager is "enabled" with no real pool needed — every method we hit
    # is monkeypatched per-test below.
    monkeypatch.setattr(
        type(mcp_manager), "enabled", property(lambda _self: True)
    )

    # AsyncSessionLocal returns a context manager that no-ops; the routes
    # forward whatever `session` they get to manager methods which are mocked.
    class _NoSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(pg, "AsyncSessionLocal", lambda: _NoSession())

    # Audit silenced — assertions on its shape live in the unit tests.
    import app.audit.manager as audit_mod

    monkeypatch.setattr(audit_mod, "log_event", AsyncMock())

    app = _make_app()
    app.dependency_overrides[get_tenant_context] = _admin_context

    with TestClient(app) as client:
        yield client, app


@pytest.fixture
def user_client(monkeypatch, admin_client):
    """Same as admin_client but with TenantContext = non-admin user."""
    from app.auth.tenant import get_tenant_context

    _client, app = admin_client
    app.dependency_overrides[get_tenant_context] = _user_context
    with TestClient(app) as client:
        yield client


# ── /catalog ──────────────────────────────────────────────────────────


class TestCatalogE2E:
    def test_get_catalog_200(self, admin_client):
        client, _ = admin_client
        res = client.get("/api/v1/mcp/catalog")
        assert res.status_code == 200
        body = res.json()
        # Stable shape
        assert "catalog" in body
        assert "mcp_enabled" in body
        # Tier-1 servers all present
        names = {e["server_name"] for e in body["catalog"]}
        assert {"slack", "github", "notion", "gdrive"}.issubset(names)
        # Each entry has the documented fields and NO credentials value
        for entry in body["catalog"]:
            assert "server_name" in entry
            assert "display_name" in entry
            assert "required_credentials" in entry
            assert isinstance(entry["required_credentials"], list)
            assert "credentials" not in entry  # only field NAMES, never values


# ── /connections list ─────────────────────────────────────────────────


class TestListConnectionsE2E:
    def test_returns_empty_when_disabled(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp import mcp_manager

        monkeypatch.setattr(
            type(mcp_manager), "enabled", property(lambda _self: False)
        )
        res = client.get("/api/v1/mcp/connections")
        assert res.status_code == 200
        assert res.json() == {"connections": [], "mcp_enabled": False}

    def test_response_strips_credentials(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp import mcp_manager

        monkeypatch.setattr(
            mcp_manager,
            "list_connections",
            AsyncMock(
                return_value=[
                    {
                        "server_name": "slack",
                        "status": "enabled",
                        "last_health_check": "2026-05-04T00:00:00Z",
                        "error_message": None,
                        "created_at": "2026-05-04T00:00:00Z",
                        "updated_at": "2026-05-04T00:00:00Z",
                        # If any field shaped like a credential leaked through
                        # serialization, the assertion below catches it.
                        "credentials": {"SLACK_BOT_TOKEN": "should-not-leak"},
                        "encrypted_config": "ciphertext",
                    }
                ]
            ),
        )
        res = client.get("/api/v1/mcp/connections")
        assert res.status_code == 200
        body = res.json()
        assert len(body["connections"]) == 1
        conn = body["connections"][0]
        assert conn["server_name"] == "slack"
        # Hard guarantees — these must NEVER appear over the wire
        assert "credentials" not in conn
        assert "encrypted_config" not in conn
        assert "should-not-leak" not in res.text


# ── /connections enable ───────────────────────────────────────────────


class TestEnableConnectionE2E:
    def test_non_admin_returns_403(self, user_client):
        res = user_client.post(
            "/api/v1/mcp/connections",
            json={
                "server_name": "slack",
                "credentials": {"SLACK_BOT_TOKEN": "x", "SLACK_TEAM_ID": "T"},
            },
        )
        assert res.status_code == 403

    def test_invalid_body_returns_422(self, admin_client):
        """FastAPI's pydantic validation kicks in BEFORE the route function.
        This proves the request schema is wired up."""
        client, _ = admin_client
        # Missing required `server_name`
        res = client.post(
            "/api/v1/mcp/connections", json={"credentials": {"x": "y"}}
        )
        assert res.status_code == 422

    def test_happy_path_returns_200_with_stripped_row(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp import mcp_manager

        monkeypatch.setattr(
            mcp_manager,
            "enable_connection",
            AsyncMock(
                return_value={
                    "server_name": "slack",
                    "status": "enabled",
                    "last_health_check": "2026-05-04T00:00:00Z",
                    "error_message": None,
                    "created_at": "2026-05-04T00:00:00Z",
                    "updated_at": "2026-05-04T00:00:00Z",
                }
            ),
        )
        res = client.post(
            "/api/v1/mcp/connections",
            json={
                "server_name": "slack",
                "credentials": {"SLACK_BOT_TOKEN": "x", "SLACK_TEAM_ID": "T"},
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["connection"]["server_name"] == "slack"
        assert body["connection"]["status"] == "enabled"
        assert "credentials" not in body["connection"]

    def test_manager_error_maps_to_400(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp.errors import MCPError
        from app.mcp import mcp_manager

        async def boom(*a, **k):
            raise MCPError(
                "missing required credentials for slack",
                extra={"missing": ["SLACK_TEAM_ID"]},
            )

        monkeypatch.setattr(mcp_manager, "enable_connection", boom)
        res = client.post(
            "/api/v1/mcp/connections",
            json={"server_name": "slack", "credentials": {"SLACK_BOT_TOKEN": "x"}},
        )
        assert res.status_code == 400
        # Stable error code is in the body — what the frontend matches against
        assert res.json()["detail"]["code"] == "mcp.error"


# ── /connections/{server}/test ────────────────────────────────────────


class TestTestConnectionE2E:
    def test_non_admin_returns_403(self, user_client):
        res = user_client.post("/api/v1/mcp/connections/slack/test")
        assert res.status_code == 403

    def test_happy_path_returns_ok_true(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp import mcp_manager

        monkeypatch.setattr(
            mcp_manager, "test_connection", AsyncMock(return_value=(True, None))
        )
        res = client.post("/api/v1/mcp/connections/slack/test")
        assert res.status_code == 200
        body = res.json()
        # Pydantic response_model serialization
        assert body == {"ok": True, "error_message": None}

    def test_capacity_error_maps_to_429(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp.errors import MCPCapacityError
        from app.mcp import mcp_manager

        async def boom(*a, **k):
            raise MCPCapacityError("pool full")

        monkeypatch.setattr(mcp_manager, "test_connection", boom)
        res = client.post("/api/v1/mcp/connections/slack/test")
        assert res.status_code == 429

    def test_crypto_error_does_not_leak_internal(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp.errors import MCPCryptoError
        from app.mcp import mcp_manager

        async def boom(*a, **k):
            raise MCPCryptoError("very specific internal detail")

        monkeypatch.setattr(mcp_manager, "test_connection", boom)
        res = client.post("/api/v1/mcp/connections/slack/test")
        assert res.status_code == 500
        # Internal detail must NOT appear in the wire body
        assert "very specific internal detail" not in res.text
        assert res.json()["detail"]["code"] == "mcp.crypto_error"


# ── /connections/{server}/disable + DELETE ────────────────────────────


class TestDisableAndRemoveE2E:
    def test_disable_non_admin_403(self, user_client):
        res = user_client.post("/api/v1/mcp/connections/slack/disable")
        assert res.status_code == 403

    def test_disable_unknown_404(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp import mcp_manager

        monkeypatch.setattr(
            mcp_manager, "disable_connection", AsyncMock(return_value=False)
        )
        res = client.post("/api/v1/mcp/connections/slack/disable")
        assert res.status_code == 404
        assert res.json()["detail"]["code"] == "mcp.connection_not_found"

    def test_disable_happy_returns_200(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp import mcp_manager

        monkeypatch.setattr(
            mcp_manager, "disable_connection", AsyncMock(return_value=True)
        )
        res = client.post("/api/v1/mcp/connections/slack/disable")
        assert res.status_code == 200
        assert res.json() == {"disabled": True}

    def test_remove_non_admin_403(self, user_client):
        res = user_client.delete("/api/v1/mcp/connections/slack")
        assert res.status_code == 403

    def test_remove_happy_returns_200(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp import mcp_manager

        monkeypatch.setattr(
            mcp_manager, "remove_connection", AsyncMock(return_value=True)
        )
        res = client.delete("/api/v1/mcp/connections/slack")
        assert res.status_code == 200
        assert res.json() == {"removed": True}


# ── /tools ─────────────────────────────────────────────────────────────


class TestListToolsE2E:
    def test_disabled_returns_empty(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp import mcp_manager

        monkeypatch.setattr(
            type(mcp_manager), "enabled", property(lambda _self: False)
        )
        res = client.get("/api/v1/mcp/tools")
        assert res.status_code == 200
        assert res.json() == {"tools": [], "mcp_enabled": False}

    def test_serializes_descriptors(self, admin_client, monkeypatch):
        client, _ = admin_client
        from app.mcp import mcp_manager
        from app.mcp.types import MCPToolDescriptor

        monkeypatch.setattr(
            mcp_manager,
            "list_tools",
            AsyncMock(
                return_value=[
                    MCPToolDescriptor(
                        server_name="slack",
                        tool_name="search_messages",
                        qualified_name="slack.search_messages",
                        description="Search Slack messages",
                        input_schema={"type": "object"},
                    ),
                ]
            ),
        )
        res = client.get("/api/v1/mcp/tools")
        assert res.status_code == 200
        body = res.json()
        assert body["mcp_enabled"] is True
        assert len(body["tools"]) == 1
        tool = body["tools"][0]
        # Pydantic response_model shape
        assert tool["qualified_name"] == "slack.search_messages"
        assert tool["server_name"] == "slack"
        assert tool["tool_name"] == "search_messages"
        assert tool["description"] == "Search Slack messages"
        assert tool["input_schema"] == {"type": "object"}


# ── HTTP method + path routing ────────────────────────────────────────


class TestRoutingE2E:
    def test_wrong_method_returns_405(self, admin_client):
        client, _ = admin_client
        # /catalog is GET-only
        res = client.post("/api/v1/mcp/catalog")
        assert res.status_code == 405

    def test_unknown_path_returns_404(self, admin_client):
        client, _ = admin_client
        res = client.get("/api/v1/mcp/this-route-does-not-exist")
        assert res.status_code == 404
