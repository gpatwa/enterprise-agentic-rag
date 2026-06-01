# services/api/app/support/store.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.support.models import (
    SupportCustomer,
    SupportSyncRun,
    SupportTicket,
)
from app.support.types import NormalizedSupportCustomer, NormalizedSupportTicket


class SupportDataStore:
    async def upsert_customer(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        customer: NormalizedSupportCustomer,
    ) -> bool:
        row = await self._get_customer(
            session,
            tenant_id=tenant_id,
            provider=customer.provider,
            external_id=customer.external_id,
        )
        created = row is None
        now = datetime.utcnow()
        if row is None:
            row = SupportCustomer(
                tenant_id=tenant_id,
                provider=customer.provider,
                external_id=customer.external_id,
                created_at=now,
            )
            session.add(row)

        row.email = customer.email
        row.name = customer.name
        row.role = customer.role
        row.raw = customer.raw or {}
        row.updated_at = now
        await session.flush()
        return created

    async def upsert_ticket(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        ticket: NormalizedSupportTicket,
    ) -> bool:
        row = await self._get_ticket(
            session,
            tenant_id=tenant_id,
            provider=ticket.provider,
            external_id=ticket.external_id,
        )
        created = row is None
        now = datetime.utcnow()
        if row is None:
            row = SupportTicket(
                tenant_id=tenant_id,
                provider=ticket.provider,
                external_id=ticket.external_id,
                first_seen_at=now,
                created_at=now,
            )
            session.add(row)

        row.subject = ticket.subject
        row.description = ticket.description
        row.status = ticket.status
        row.priority = ticket.priority
        row.category = ticket.category
        row.channel = ticket.channel
        row.requester_external_id = ticket.requester_external_id
        row.assignee_external_id = ticket.assignee_external_id
        row.organization_external_id = ticket.organization_external_id
        row.tags = ticket.tags
        row.custom_fields = self._custom_fields(ticket.raw)
        row.raw = ticket.raw
        row.source_url = ticket.source_url
        row.created_at_external = ticket.created_at_external
        row.updated_at_external = ticket.updated_at_external
        row.last_synced_at = now
        row.updated_at = now
        await session.flush()
        return created

    async def list_tickets(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SupportTicket], int]:
        conditions = [SupportTicket.tenant_id == tenant_id]
        if provider:
            conditions.append(SupportTicket.provider == provider)
        if status:
            conditions.append(SupportTicket.status == status)

        total = await session.scalar(
            select(func.count(SupportTicket.id)).where(and_(*conditions))
        )
        result = await session.execute(
            select(SupportTicket)
            .where(and_(*conditions))
            .order_by(desc(SupportTicket.updated_at_external), desc(SupportTicket.updated_at))
            .offset(max(offset, 0))
            .limit(min(max(limit, 1), 200))
        )
        return list(result.scalars().all()), int(total or 0)

    async def list_sync_runs(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str | None = None,
        limit: int = 50,
    ) -> list[SupportSyncRun]:
        conditions = [SupportSyncRun.tenant_id == tenant_id]
        if provider:
            conditions.append(SupportSyncRun.provider == provider)

        result = await session.execute(
            select(SupportSyncRun)
            .where(and_(*conditions))
            .order_by(desc(SupportSyncRun.started_at))
            .limit(min(max(limit, 1), 100))
        )
        return list(result.scalars().all())

    async def latest_success_cursor(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
    ) -> str | None:
        result = await session.execute(
            select(SupportSyncRun.cursor_finished_at)
            .where(
                SupportSyncRun.tenant_id == tenant_id,
                SupportSyncRun.provider == provider,
                SupportSyncRun.status == "succeeded",
                SupportSyncRun.cursor_finished_at.is_not(None),
            )
            .order_by(desc(SupportSyncRun.started_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_ticket(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
        external_id: str,
    ) -> SupportTicket | None:
        result = await session.execute(
            select(SupportTicket).where(
                SupportTicket.tenant_id == tenant_id,
                SupportTicket.provider == provider,
                SupportTicket.external_id == external_id,
            )
        )
        return result.scalars().first()

    async def _get_customer(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
        external_id: str,
    ) -> SupportCustomer | None:
        result = await session.execute(
            select(SupportCustomer).where(
                SupportCustomer.tenant_id == tenant_id,
                SupportCustomer.provider == provider,
                SupportCustomer.external_id == external_id,
            )
        )
        return result.scalars().first()

    def _custom_fields(self, raw: dict[str, Any]) -> dict[str, Any]:
        custom_fields = raw.get("custom_fields")
        if isinstance(custom_fields, list):
            return {
                str(item.get("id")): item.get("value")
                for item in custom_fields
                if isinstance(item, dict) and item.get("id") is not None
            }
        if isinstance(custom_fields, dict):
            return custom_fields
        return {}


support_data_store = SupportDataStore()
