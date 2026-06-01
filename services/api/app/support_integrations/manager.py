# services/api/app/support_integrations/manager.py
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.support_integrations.catalog import SupportIntegrationCatalog
from app.support_integrations.clients import (
    ConnectorConfigError,
    IntercomDirectClient,
    IntercomNangoClient,
    ZendeskDirectClient,
    ZendeskNangoClient,
)
from app.support_integrations.models import SupportIntegrationConnection
from app.support_integrations.types import (
    SupportAuthMode,
    SupportConnectionStatus,
    SupportProvider,
    SupportTicketPreview,
)

logger = logging.getLogger(__name__)


class SupportIntegrationError(RuntimeError):
    pass


class SupportIntegrationManager:
    @property
    def enabled(self) -> bool:
        return settings.SUPPORT_INTEGRATIONS_ENABLED

    async def list_connections(
        self, session: AsyncSession, *, tenant_id: str
    ) -> list[dict[str, Any]]:
        result = await session.execute(
            select(SupportIntegrationConnection)
            .where(SupportIntegrationConnection.tenant_id == tenant_id)
            .order_by(SupportIntegrationConnection.provider.asc())
        )
        return [self._row_to_dict(row) for row in result.scalars().all()]

    async def get_connection(
        self, session: AsyncSession, *, tenant_id: str, provider: str
    ) -> SupportIntegrationConnection | None:
        result = await session.execute(
            select(SupportIntegrationConnection).where(
                SupportIntegrationConnection.tenant_id == tenant_id,
                SupportIntegrationConnection.provider == provider,
            )
        )
        return result.scalars().first()

    async def upsert_connection(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
        auth_mode: str,
        nango_connection_id: str | None = None,
        provider_config_key: str | None = None,
        external_account_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_provider(provider)
        auth_mode = self._validate_auth_mode(auth_mode)
        entry = SupportIntegrationCatalog.get(provider)
        if entry is None:
            raise SupportIntegrationError(f"unsupported provider: {provider}")

        if auth_mode == SupportAuthMode.NANGO.value and not nango_connection_id:
            raise SupportIntegrationError("nango_connection_id is required for Nango auth")

        provider_config_key = provider_config_key or entry.nango_provider_config_key
        now = datetime.utcnow()
        row = await self.get_connection(session, tenant_id=tenant_id, provider=provider)

        if row is None:
            row = SupportIntegrationConnection(
                tenant_id=tenant_id,
                provider=provider,
                auth_mode=auth_mode,
                status=SupportConnectionStatus.PENDING.value,
                nango_connection_id=nango_connection_id,
                provider_config_key=provider_config_key,
                external_account_id=external_account_id,
                metadata_=metadata or {},
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.auth_mode = auth_mode
            row.status = SupportConnectionStatus.PENDING.value
            row.nango_connection_id = nango_connection_id
            row.provider_config_key = provider_config_key
            row.external_account_id = external_account_id
            row.metadata_ = metadata or {}
            row.error_message = None
            row.updated_at = now

        await session.commit()
        await session.refresh(row)
        return self._row_to_dict(row)

    async def delete_connection(
        self, session: AsyncSession, *, tenant_id: str, provider: str
    ) -> bool:
        row = await self.get_connection(session, tenant_id=tenant_id, provider=provider)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True

    async def test_connection(
        self, session: AsyncSession, *, tenant_id: str, provider: str
    ) -> dict[str, Any]:
        row = await self.get_connection(session, tenant_id=tenant_id, provider=provider)
        if row is None:
            raise SupportIntegrationError(f"{provider} is not connected")

        try:
            result = await self._client_for(row).test()
            row.status = SupportConnectionStatus.CONNECTED.value
            row.last_health_check = datetime.utcnow()
            row.error_message = None
            await session.commit()
            await session.refresh(row)
            return {"ok": True, "connection": self._row_to_dict(row), **result}
        except Exception as e:
            message = self._safe_error_message(e)
            logger.warning("support connector test failed provider=%s: %s", provider, message)
            row.status = SupportConnectionStatus.ERROR.value
            row.last_health_check = datetime.utcnow()
            row.error_message = message
            await session.commit()
            await session.refresh(row)
            return {"ok": False, "connection": self._row_to_dict(row), "error_message": message}

    async def list_ticket_previews(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
        limit: int = 10,
    ) -> list[SupportTicketPreview]:
        row = await self.get_connection(session, tenant_id=tenant_id, provider=provider)
        if row is None:
            raise SupportIntegrationError(f"{provider} is not connected")
        return await self._client_for(row).list_tickets(limit=limit)

    async def source_health(self, session: AsyncSession, *, tenant_id: str) -> list[dict[str, Any]]:
        rows_by_provider = {
            row["provider"]: row for row in await self.list_connections(session, tenant_id=tenant_id)
        }
        sources: list[dict[str, Any]] = []
        for entry in SupportIntegrationCatalog.all():
            row = rows_by_provider.get(entry.provider)
            if row is None:
                sources.append(
                    {
                        "type": entry.provider,
                        "name": entry.display_name,
                        "status": "not_connected",
                    }
                )
                continue
            sources.append(
                {
                    "type": entry.provider,
                    "name": entry.display_name,
                    "status": "fresh" if row["status"] == "connected" else "error",
                    "last_synced_at": row.get("last_health_check"),
                }
            )
        return sources

    def _client_for(self, row: SupportIntegrationConnection):
        provider = row.provider
        auth_mode = row.auth_mode
        provider_config_key = row.provider_config_key or self._default_provider_config_key(provider)

        if provider == SupportProvider.ZENDESK.value:
            if auth_mode == SupportAuthMode.NANGO.value:
                return ZendeskNangoClient(
                    connection_id=row.nango_connection_id or "",
                    provider_config_key=provider_config_key,
                )
            if auth_mode == SupportAuthMode.DIRECT_ENV.value:
                return ZendeskDirectClient()

        if provider == SupportProvider.INTERCOM.value:
            if auth_mode == SupportAuthMode.NANGO.value:
                return IntercomNangoClient(
                    connection_id=row.nango_connection_id or "",
                    provider_config_key=provider_config_key,
                )
            if auth_mode == SupportAuthMode.DIRECT_ENV.value:
                return IntercomDirectClient()

        raise SupportIntegrationError(f"unsupported connector mode: {provider}/{auth_mode}")

    def _default_provider_config_key(self, provider: str) -> str:
        entry = SupportIntegrationCatalog.get(provider)
        if entry is None:
            raise SupportIntegrationError(f"unsupported provider: {provider}")
        return entry.nango_provider_config_key

    def _validate_provider(self, provider: str) -> str:
        if provider not in SupportIntegrationCatalog.names():
            raise SupportIntegrationError(f"unsupported provider: {provider}")
        return provider

    def _validate_auth_mode(self, auth_mode: str) -> str:
        values = {mode.value for mode in SupportAuthMode}
        if auth_mode not in values:
            raise SupportIntegrationError(f"unsupported auth mode: {auth_mode}")
        return auth_mode

    def _row_to_dict(self, row: SupportIntegrationConnection) -> dict[str, Any]:
        return {
            "provider": row.provider,
            "auth_mode": row.auth_mode,
            "status": row.status,
            "nango_connection_id": row.nango_connection_id,
            "provider_config_key": row.provider_config_key,
            "external_account_id": row.external_account_id,
            "metadata": row.metadata_ or {},
            "last_health_check": self._dt(row.last_health_check),
            "error_message": row.error_message,
            "created_at": self._dt(row.created_at),
            "updated_at": self._dt(row.updated_at),
        }

    def _dt(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.replace(microsecond=0).isoformat() + "Z"

    def _safe_error_message(self, exc: Exception) -> str:
        if isinstance(exc, ConnectorConfigError):
            return str(exc)
        return str(exc)[:300] or exc.__class__.__name__


support_integration_manager = SupportIntegrationManager()
