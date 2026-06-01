# services/api/app/support/indexer.py
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.support.documents import SupportIndexDocument, chunk_text, ticket_to_document
from app.support.models import SupportIndexRecord
from app.support.store import support_data_store

logger = logging.getLogger(__name__)

_vectordb_client = None
_embed_client = None


class SupportIndexError(RuntimeError):
    pass


def set_clients(vectordb, embedder) -> None:
    """Called once during app startup to inject vector and embedding clients."""
    global _vectordb_client, _embed_client
    _vectordb_client = vectordb
    _embed_client = embedder


class SupportIndexer:
    async def index_tickets(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        provider: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._require_clients()
        tickets, total = await support_data_store.list_tickets(
            session,
            tenant_id=tenant_id,
            provider=provider,
            limit=limit,
            offset=0,
        )
        summary: dict[str, Any] = {
            "tenant_id": tenant_id,
            "provider": provider,
            "tickets_seen": len(tickets),
            "tickets_total": total,
            "indexed": 0,
            "skipped": 0,
            "chunks": 0,
            "errors": [],
        }
        vector_size: int | None = None

        for ticket in tickets:
            document = ticket_to_document(ticket)
            try:
                record = await self._get_record(session, tenant_id=tenant_id, document=document)
                if self._is_current(record, document):
                    summary["skipped"] += 1
                    continue

                chunks = chunk_text(document.text)
                if not chunks:
                    await self._upsert_record(
                        session,
                        tenant_id=tenant_id,
                        document=document,
                        chunk_count=0,
                    )
                    summary["skipped"] += 1
                    continue

                embeddings = await _embed_client.embed_documents(chunks)
                if len(embeddings) != len(chunks):
                    raise SupportIndexError(
                        f"embedding count mismatch for {document.provider}:{document.source_id}"
                    )
                if not embeddings or not embeddings[0]:
                    raise SupportIndexError(
                        f"empty embedding returned for {document.provider}:{document.source_id}"
                    )

                current_vector_size = len(embeddings[0])
                if vector_size != current_vector_size:
                    await _vectordb_client.create_collection(
                        settings.SUPPORT_INDEX_COLLECTION,
                        vector_size=current_vector_size,
                    )
                    vector_size = current_vector_size

                delete_filter = self._source_filter(tenant_id=tenant_id, document=document)
                await _vectordb_client.delete_by_filter(settings.SUPPORT_INDEX_COLLECTION, delete_filter)
                await _vectordb_client.upsert(
                    settings.SUPPORT_INDEX_COLLECTION,
                    self._points(document=document, chunks=chunks, embeddings=embeddings),
                )
                await self._upsert_record(
                    session,
                    tenant_id=tenant_id,
                    document=document,
                    chunk_count=len(chunks),
                )
                summary["indexed"] += 1
                summary["chunks"] += len(chunks)
            except Exception as e:
                logger.warning(
                    "support ticket indexing failed for tenant=%s provider=%s source_id=%s: %s",
                    tenant_id,
                    document.provider,
                    document.source_id,
                    e,
                    exc_info=True,
                )
                summary["errors"].append(
                    {
                        "provider": document.provider,
                        "source_type": document.source_type,
                        "source_id": document.source_id,
                        "error": str(e),
                    }
                )

        await session.commit()
        return summary

    async def search(
        self,
        *,
        tenant_id: str,
        query: str,
        provider: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        self._require_clients()
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if provider:
            filters["provider"] = provider
        if status:
            filters["status"] = status

        try:
            vector = await _embed_client.embed_query(query)
            results = await _vectordb_client.search(
                settings.SUPPORT_INDEX_COLLECTION,
                vector,
                limit=limit,
                filters=filters,
            )
        except Exception as e:
            logger.warning("support index search failed for tenant=%s: %s", tenant_id, e, exc_info=True)
            raise SupportIndexError("support index is unavailable or has not been initialized") from e

        return [self._result_to_response(result) for result in results]

    def _require_clients(self) -> None:
        if _vectordb_client is None or _embed_client is None:
            raise SupportIndexError("support index clients are not configured")

    async def _get_record(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        document: SupportIndexDocument,
    ) -> SupportIndexRecord | None:
        result = await session.execute(
            select(SupportIndexRecord).where(
                SupportIndexRecord.tenant_id == tenant_id,
                SupportIndexRecord.provider == document.provider,
                SupportIndexRecord.source_type == document.source_type,
                SupportIndexRecord.source_id == document.source_id,
            )
        )
        return result.scalars().first()

    def _is_current(
        self,
        record: SupportIndexRecord | None,
        document: SupportIndexDocument,
    ) -> bool:
        return bool(
            record
            and record.content_hash == document.content_hash
            and record.index_version == settings.SUPPORT_INDEX_VERSION
        )

    async def _upsert_record(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        document: SupportIndexDocument,
        chunk_count: int,
    ) -> None:
        record = await self._get_record(session, tenant_id=tenant_id, document=document)
        now = datetime.utcnow()
        if record is None:
            record = SupportIndexRecord(
                tenant_id=tenant_id,
                provider=document.provider,
                source_type=document.source_type,
                source_id=document.source_id,
                created_at=now,
            )
            session.add(record)

        record.content_hash = document.content_hash
        record.chunk_count = chunk_count
        record.index_version = settings.SUPPORT_INDEX_VERSION
        record.indexed_at = now
        record.updated_at = now
        await session.flush()

    def _points(
        self,
        *,
        document: SupportIndexDocument,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> list[dict[str, Any]]:
        chunk_count = len(chunks)
        points = []
        for idx, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            payload = {
                **document.metadata,
                "title": document.title,
                "text": chunk,
                "content_hash": document.content_hash,
                "chunk_index": idx,
                "chunk_count": chunk_count,
            }
            points.append(
                {
                    "id": self._point_id(document=document, chunk_index=idx),
                    "vector": vector,
                    "payload": payload,
                }
            )
        return points

    def _point_id(self, *, document: SupportIndexDocument, chunk_index: int) -> str:
        stable_key = ":".join(
            [
                document.metadata["tenant_id"],
                document.provider,
                document.source_type,
                document.source_id,
                settings.SUPPORT_INDEX_VERSION,
                str(chunk_index),
            ]
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, stable_key))

    def _source_filter(self, *, tenant_id: str, document: SupportIndexDocument) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "provider": document.provider,
            "source_type": document.source_type,
            "source_id": document.source_id,
        }

    def _result_to_response(self, result: dict[str, Any]) -> dict[str, Any]:
        payload = result.get("payload") or {}
        return {
            "id": str(result.get("id")),
            "score": result.get("score"),
            "provider": payload.get("provider"),
            "source_type": payload.get("source_type"),
            "source_id": payload.get("source_id"),
            "title": payload.get("title") or payload.get("subject"),
            "text": payload.get("text", ""),
            "status": payload.get("status"),
            "priority": payload.get("priority"),
            "tags": payload.get("tags") or [],
            "source_url": payload.get("source_url"),
            "chunk_index": payload.get("chunk_index"),
            "chunk_count": payload.get("chunk_count"),
        }


support_indexer = SupportIndexer()
