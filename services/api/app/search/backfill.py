from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.search.schema import SupportSearchDocument
from app.search.support_mapper import map_article, map_comment, map_ticket
from app.support.models import (
    SupportArticle,
    SupportSearchCheckpoint,
    SupportSearchOutboxEvent,
    SupportTicket,
    SupportTicketComment,
)

SOURCE_TYPES = ("ticket", "comment", "article")
_SOURCE_SPECS: dict[str, tuple[type[Any], Any]] = {
    "ticket": (SupportTicket, map_ticket),
    "comment": (SupportTicketComment, map_comment),
    "article": (SupportArticle, map_article),
}


@dataclass
class BackfillReport:
    tenant_id: str
    provider: str
    dry_run: bool
    records_seen: int = 0
    events_queued: int = 0
    events_skipped: int = 0
    checkpoints_advanced: int = 0
    streams: dict[str, dict[str, int | str | None]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "provider": self.provider,
            "dry_run": self.dry_run,
            "records_seen": self.records_seen,
            "events_queued": self.events_queued,
            "events_skipped": self.events_skipped,
            "checkpoints_advanced": self.checkpoints_advanced,
            "streams": self.streams,
        }


class SupportSearchBackfill:
    """Project canonical support rows into the durable search outbox."""

    async def run(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
        source_types: Sequence[str] = SOURCE_TYPES,
        batch_size: int = 100,
        max_records: int | None = None,
        dry_run: bool = False,
    ) -> BackfillReport:
        normalized_types = _normalize_source_types(source_types)
        report = BackfillReport(
            tenant_id=tenant_id,
            provider=provider,
            dry_run=dry_run,
        )
        remaining = max_records if max_records is None else max(max_records, 0)

        for source_type in normalized_types:
            if remaining == 0:
                break
            stream_report = await self._run_stream(
                session,
                tenant_id=tenant_id,
                provider=provider,
                source_type=source_type,
                batch_size=batch_size,
                max_records=remaining,
                dry_run=dry_run,
                report=report,
            )
            report.streams[source_type] = stream_report
            if remaining is not None:
                remaining = max(remaining - int(stream_report["records_seen"] or 0), 0)
        return report

    async def _run_stream(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str,
        source_type: str,
        batch_size: int,
        max_records: int | None,
        dry_run: bool,
        report: BackfillReport,
    ) -> dict[str, int | str | None]:
        checkpoint = await _get_checkpoint(
            session,
            tenant_id=tenant_id,
            provider=provider,
            stream_key=source_type,
        )
        after_id = _cursor_id(checkpoint.cursor if checkpoint else None)
        seen = 0
        queued = 0
        skipped = 0
        last_cursor: str | None = checkpoint.cursor if checkpoint else None
        last_event_id: str | None = checkpoint.last_event_id if checkpoint else None

        while max_records is None or seen < max_records:
            take = min(max(batch_size, 1), 500)
            if max_records is not None:
                take = min(take, max_records - seen)
            rows = await _load_source_batch(
                session,
                tenant_id=tenant_id,
                provider=provider,
                source_type=source_type,
                after_id=after_id,
                limit=take,
            )
            if not rows:
                break

            for row in rows:
                document = _SOURCE_SPECS[source_type][1](row)
                seen += 1
                report.records_seen += 1
                last_cursor = str(row.id)
                after_id = int(row.id)
                if dry_run:
                    continue

                event_key = _event_key(
                    tenant_id,
                    provider,
                    source_type,
                    document.source_id,
                    document.content_version,
                )
                existing = await session.scalar(
                    select(SupportSearchOutboxEvent.id).where(
                        SupportSearchOutboxEvent.idempotency_key == event_key
                    )
                )
                if existing is not None:
                    skipped += 1
                    report.events_skipped += 1
                    continue

                event = SupportSearchOutboxEvent(
                    idempotency_key=event_key,
                    tenant_id=tenant_id,
                    provider=provider,
                    event_type="upsert",
                    source_type=source_type,
                    source_id=document.source_id,
                    content_version=document.content_version,
                    payload={"document": document.model_dump(mode="json"), "backfill": True},
                    status="queued",
                    attempt_count=0,
                    max_attempts=5,
                    available_at=datetime.utcnow(),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                session.add(event)
                await session.flush()
                last_event_id = str(event.id)
                queued += 1
                report.events_queued += 1

            if not dry_run:
                checkpoint = checkpoint or SupportSearchCheckpoint(
                    tenant_id=tenant_id,
                    provider=provider,
                    stream_key=source_type,
                )
                checkpoint.cursor = last_cursor
                checkpoint.last_event_id = last_event_id
                checkpoint.last_source_updated_at = _source_updated_at(rows[-1])
                checkpoint.updated_at = datetime.utcnow()
                session.add(checkpoint)
                await session.commit()
                report.checkpoints_advanced += 1
                checkpoint = await _get_checkpoint(
                    session,
                    tenant_id=tenant_id,
                    provider=provider,
                    stream_key=source_type,
                )

            if len(rows) < take:
                break

        return {
            "records_seen": seen,
            "events_queued": queued,
            "events_skipped": skipped,
            "cursor": last_cursor,
        }


async def iter_source_documents(
    session: AsyncSession,
    *,
    tenant_id: str | None,
    provider: str,
    source_types: Sequence[str] = SOURCE_TYPES,
    batch_size: int = 500,
) -> AsyncIterator[SupportSearchDocument]:
    """Yield canonical source documents in stable, bounded batches."""
    for source_type in _normalize_source_types(source_types):
        after_id = 0
        while True:
            rows = await _load_source_batch(
                session,
                tenant_id=tenant_id,
                provider=provider,
                source_type=source_type,
                after_id=after_id,
                limit=min(max(batch_size, 1), 500),
            )
            if not rows:
                break
            for row in rows:
                after_id = int(row.id)
                yield _SOURCE_SPECS[source_type][1](row)
            if len(rows) < min(max(batch_size, 1), 500):
                break


async def _load_source_batch(
    session: AsyncSession,
    *,
    tenant_id: str | None,
    provider: str,
    source_type: str,
    after_id: int,
    limit: int,
) -> list[Any]:
    model = _SOURCE_SPECS[source_type][0]
    conditions = [model.provider == provider, model.id > after_id]
    if tenant_id is not None:
        conditions.append(model.tenant_id == tenant_id)
    result = await session.execute(
        select(model)
        .where(*conditions)
        .order_by(model.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def _get_checkpoint(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    stream_key: str,
) -> SupportSearchCheckpoint | None:
    result = await session.execute(
        select(SupportSearchCheckpoint).where(
            SupportSearchCheckpoint.tenant_id == tenant_id,
            SupportSearchCheckpoint.provider == provider,
            SupportSearchCheckpoint.stream_key == stream_key,
        )
    )
    return result.scalars().first()


def _normalize_source_types(source_types: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(value.strip().lower() for value in source_types))
    unsupported = sorted(set(normalized) - set(SOURCE_TYPES))
    if unsupported:
        raise ValueError(f"unsupported support backfill source types: {', '.join(unsupported)}")
    return normalized


def _cursor_id(cursor: str | None) -> int:
    try:
        return max(int(cursor or "0"), 0)
    except ValueError:
        return 0


def _event_key(
    tenant_id: str,
    provider: str,
    source_type: str,
    source_id: str,
    content_version: str,
) -> str:
    value = f"backfill:{tenant_id}:{provider}:{source_type}:{source_id}:{content_version}"
    if len(value) <= 255:
        return value
    return f"backfill:{source_type}:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _source_updated_at(row: Any) -> datetime | None:
    return getattr(row, "updated_at_external", None) or getattr(row, "updated_at", None)


support_search_backfill = SupportSearchBackfill()
