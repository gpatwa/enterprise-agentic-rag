from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.search.models import SearchScope
from app.search.schema import SupportSearchDocument
from app.search.support_mapper import map_article, map_comment, map_ticket
from app.support.models import (
    SupportArticle,
    SupportSearchOutboxEvent,
    SupportTicket,
    SupportTicketComment,
)

SessionFactory = Callable[[], AsyncSession]


class SearchIndexingError(RuntimeError):
    """An outbox event could not be applied to the search provider."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class SupportSearchEventProcessor:
    """Apply one durable support-search event to an injected provider."""

    def __init__(self, provider: Any, session_factory: SessionFactory) -> None:
        self.provider = provider
        self.session_factory = session_factory

    async def __call__(self, event: SupportSearchOutboxEvent) -> None:
        event_type = (event.event_type or "upsert").strip().lower()
        if event_type in {"delete", "tombstone", "remove"}:
            await self._delete(event)
            return
        if event_type not in {"upsert", "create", "update", "permission_change"}:
            raise SearchIndexingError(
                f"unsupported search outbox event type: {event.event_type}",
                retryable=False,
            )
        await self._upsert(event)

    async def _upsert(self, event: SupportSearchOutboxEvent) -> None:
        document = await self._document_for_event(event)
        result = await self.provider.upsert([document])
        if result.failed:
            error = result.errors[0]
            raise SearchIndexingError(
                f"{error.code}: {error.message}",
                retryable=error.retryable,
            )

    async def _delete(self, event: SupportSearchOutboxEvent) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        document_id = payload.get("document_id") or _document_id(
            event.tenant_id,
            event.provider,
            event.source_type,
            event.source_id,
        )
        scope = SearchScope(
            tenant_id=event.tenant_id,
            principal_id="search-worker",
            purpose="search-indexing",
            acl_tokens=(f"tenant:{event.tenant_id}",),
        )
        result = await self.provider.delete([str(document_id)], scope=scope)
        if result.failed:
            error = result.errors[0]
            raise SearchIndexingError(
                f"{error.code}: {error.message}",
                retryable=error.retryable,
            )

    async def _document_for_event(self, event: SupportSearchOutboxEvent) -> SupportSearchDocument:
        payload = event.payload if isinstance(event.payload, dict) else {}
        raw_document = payload.get("document")
        if isinstance(raw_document, dict):
            return SupportSearchDocument.model_validate(raw_document)

        async with self.session_factory() as session:
            source = await _load_source(session, event)
        if source is None:
            raise SearchIndexingError(
                f"source record not found for {event.source_type}:{event.source_id}",
                retryable=False,
            )
        return _map_source(source, event.source_type)


async def _load_source(session: AsyncSession, event: SupportSearchOutboxEvent) -> Any | None:
    model = {
        "ticket": SupportTicket,
        "comment": SupportTicketComment,
        "article": SupportArticle,
    }.get(event.source_type)
    if model is None:
        raise SearchIndexingError(
            f"unsupported search source type: {event.source_type}",
            retryable=False,
        )
    result = await session.execute(
        select(model)
        .where(
            model.tenant_id == event.tenant_id,
            model.provider == event.provider,
            model.external_id == event.source_id,
        )
        .limit(1)
    )
    return result.scalars().first()


def _map_source(source: Any, source_type: str) -> SupportSearchDocument:
    if source_type == "ticket":
        return map_ticket(source)
    if source_type == "comment":
        return map_comment(source)
    if source_type == "article":
        return map_article(source)
    raise SearchIndexingError(
        f"unsupported search source type: {source_type}",
        retryable=False,
    )


def _document_id(tenant_id: str, provider: str, source_type: str, source_id: str) -> str:
    value = f"{tenant_id}:{provider}:{source_type}:{source_id}"
    if len(value) <= 255:
        return value
    return f"{source_type}:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
