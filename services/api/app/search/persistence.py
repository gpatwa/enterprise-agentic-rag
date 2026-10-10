from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Integer, String, UniqueConstraint, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.postgres import Base
from app.search.events import SearchInteractionEvent


class SearchInteractionEventRecord(Base):
    __tablename__ = "search_interaction_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(255), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    tenant_id = Column(String(255), nullable=False)
    principal_pseudonym = Column(String(255), nullable=False)
    purpose = Column(String(255), nullable=False)
    kind = Column(String(64), nullable=False)
    request_id = Column(String(255), nullable=True)
    document_id = Column(String(255), nullable=True)
    query_hash = Column(String(128), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consent_granted = Column(Boolean, nullable=False, default=False)
    metadata_json = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_search_interaction_idempotency"),
        Index("idx_search_interaction_tenant_expiry", "tenant_id", "expires_at"),
        Index("idx_search_interaction_tenant_document", "tenant_id", "document_id"),
    )


async def persist_interaction_event(session: AsyncSession, event: SearchInteractionEvent) -> bool:
    if not event.consent_granted:
        return False
    existing = await session.scalar(
        select(SearchInteractionEventRecord.id).where(
            SearchInteractionEventRecord.tenant_id == event.tenant_id,
            SearchInteractionEventRecord.idempotency_key == event.idempotency_key,
        )
    )
    if existing is not None:
        return False
    session.add(
        SearchInteractionEventRecord(
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            tenant_id=event.tenant_id,
            principal_pseudonym=event.principal_pseudonym,
            purpose=event.purpose,
            kind=event.kind.value,
            request_id=event.request_id,
            document_id=event.document_id,
            query_hash=event.query_hash,
            occurred_at=event.occurred_at.astimezone(timezone.utc),
            expires_at=event.expires_at.astimezone(timezone.utc),
            consent_granted=True,
            metadata_json=event.metadata,
        )
    )
    await session.flush()
    return True


async def delete_expired_interaction_events(session: AsyncSession, *, now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    result = await session.execute(delete(SearchInteractionEventRecord).where(SearchInteractionEventRecord.expires_at <= current))
    await session.flush()
    return int(result.rowcount or 0)


async def delete_tenant_interaction_events(session: AsyncSession, *, tenant_id: str) -> int:
    result = await session.execute(delete(SearchInteractionEventRecord).where(SearchInteractionEventRecord.tenant_id == tenant_id))
    await session.flush()
    return int(result.rowcount or 0)
