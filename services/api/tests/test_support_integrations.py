# services/api/tests/test_support_integrations.py
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


def _ctx(role: str = "admin", tenant_id: str = "t1", user_id: str = "alice"):
    from app.auth.tenant import TenantContext

    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        permissions=[],
    )


class TestSupportCatalog:
    def test_first_wave_connectors_are_zendesk_and_intercom(self):
        from app.support_integrations.catalog import SupportIntegrationCatalog

        entries = SupportIntegrationCatalog.all()
        names = {entry.provider for entry in entries}
        assert names == {"zendesk", "intercom"}
        assert all("nango" in entry.auth_modes for entry in entries)
        assert all("direct_env" in entry.auth_modes for entry in entries)

    @pytest.mark.asyncio
    async def test_catalog_route_exposes_no_credentials(self):
        from app.routes.support_integrations import get_catalog

        body = await get_catalog(_ctx(role="user"))
        assert body["support_integrations_enabled"] is True
        providers = {entry["provider"] for entry in body["catalog"]}
        assert providers == {"zendesk", "intercom"}
        for entry in body["catalog"]:
            assert "api_token" not in entry
            assert "access_token" not in entry
            assert isinstance(entry["direct_env_vars"], list)


class TestSupportConnectionRoutes:
    @pytest.mark.asyncio
    async def test_upsert_requires_admin_before_touching_db(self):
        from app.routes.support_integrations import (
            UpsertSupportConnectionRequest,
            upsert_connection,
        )

        with pytest.raises(HTTPException) as exc:
            await upsert_connection(
                UpsertSupportConnectionRequest(
                    provider="zendesk",
                    auth_mode="nango",
                    nango_connection_id="conn_123",
                ),
                _ctx(role="user"),
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_upsert_forwards_clean_metadata(self, monkeypatch):
        import app.memory.postgres as pg
        import app.routes.support_integrations as routes

        class _NoSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

        fake_manager = type(
            "FakeSupportManager",
            (),
            {
                "enabled": True,
                "upsert_connection": AsyncMock(
                    return_value={
                        "provider": "intercom",
                        "auth_mode": "nango",
                        "status": "pending",
                        "nango_connection_id": "conn_intercom",
                        "provider_config_key": "intercom",
                        "external_account_id": None,
                        "metadata": {},
                        "last_health_check": None,
                        "error_message": None,
                        "created_at": "2026-05-30T00:00:00Z",
                        "updated_at": "2026-05-30T00:00:00Z",
                    }
                ),
            },
        )()

        monkeypatch.setattr(pg, "AsyncSessionLocal", lambda: _NoSession())
        monkeypatch.setattr(routes, "support_integration_manager", fake_manager)
        monkeypatch.setattr(routes.audit_mgr, "log_event", AsyncMock())

        body = await routes.upsert_connection(
            routes.UpsertSupportConnectionRequest(
                provider="intercom",
                auth_mode="nango",
                nango_connection_id="conn_intercom",
                provider_config_key="intercom",
            ),
            _ctx(),
        )

        assert body["connection"]["provider"] == "intercom"
        fake_manager.upsert_connection.assert_awaited_once()
        kwargs = fake_manager.upsert_connection.await_args.kwargs
        assert kwargs["tenant_id"] == "t1"
        assert kwargs["provider"] == "intercom"
        assert kwargs["nango_connection_id"] == "conn_intercom"


class TestDirectClients:
    @pytest.mark.asyncio
    async def test_zendesk_direct_client_fails_closed_without_env(self, monkeypatch):
        from app.support_integrations.clients import ConnectorConfigError, ZendeskDirectClient

        monkeypatch.setattr("app.support_integrations.clients.settings.ZENDESK_SUBDOMAIN", None)
        monkeypatch.setattr("app.support_integrations.clients.settings.ZENDESK_EMAIL", None)
        monkeypatch.setattr("app.support_integrations.clients.settings.ZENDESK_API_TOKEN", None)

        client = ZendeskDirectClient()
        assert client.configured is False
        with pytest.raises(ConnectorConfigError):
            client._headers()

    @pytest.mark.asyncio
    async def test_intercom_direct_client_fails_closed_without_env(self, monkeypatch):
        from app.support_integrations.clients import ConnectorConfigError, IntercomDirectClient

        monkeypatch.setattr("app.support_integrations.clients.settings.INTERCOM_ACCESS_TOKEN", None)

        client = IntercomDirectClient()
        assert client.configured is False
        with pytest.raises(ConnectorConfigError):
            client._headers()
