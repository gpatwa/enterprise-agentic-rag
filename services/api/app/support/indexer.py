# services/api/app/support/indexer.py
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.support.documents import (
    SupportIndexDocument,
    article_to_document,
    chunk_text,
    comment_to_document,
    ticket_to_document,
)
from app.support.lexical import support_lexical_search
from app.support.models import SupportIndexRecord
from app.support.store import support_data_store
from app.tracing import record_span_error, set_span_attributes, start_span

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
        with start_span(
            "support.index",
            tenant_id=tenant_id,
            provider=provider or "all",
            limit=limit,
        ) as span:
            self._require_clients()
            tickets, tickets_total = await support_data_store.list_tickets(
                session,
                tenant_id=tenant_id,
                provider=provider,
                limit=limit,
                offset=0,
            )
            comments, comments_total = await support_data_store.list_comments(
                session,
                tenant_id=tenant_id,
                provider=provider,
                limit=limit * 5,
                offset=0,
            )
            articles, articles_total = await support_data_store.list_articles(
                session,
                tenant_id=tenant_id,
                provider=provider,
                limit=limit,
                offset=0,
            )
            documents = [ticket_to_document(ticket) for ticket in tickets]
            documents.extend(comment_to_document(comment) for comment in comments)
            documents.extend(article_to_document(article) for article in articles)

            summary: dict[str, Any] = {
                "tenant_id": tenant_id,
                "provider": provider,
                "tickets_seen": len(tickets),
                "tickets_total": tickets_total,
                "comments_seen": len(comments),
                "comments_total": comments_total,
                "articles_seen": len(articles),
                "articles_total": articles_total,
                "indexed": 0,
                "skipped": 0,
                "chunks": 0,
                "errors": [],
            }
            vector_size: int | None = None

            for document in documents:
                try:
                    result = await self._index_document(
                        session,
                        tenant_id=tenant_id,
                        document=document,
                        vector_size=vector_size,
                    )
                    vector_size = result["vector_size"]
                    if result["indexed"]:
                        summary["indexed"] += 1
                        summary["chunks"] += result["chunks"]
                    else:
                        summary["skipped"] += 1
                except Exception as e:
                    record_span_error(span, e)
                    logger.warning(
                        "support indexing failed for tenant=%s provider=%s source_type=%s source_id=%s: %s",
                        tenant_id,
                        document.provider,
                        document.source_type,
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
            set_span_attributes(
                span,
                tickets_total=tickets_total,
                comments_total=comments_total,
                articles_total=articles_total,
                documents_total=len(documents),
                indexed=summary["indexed"],
                skipped=summary["skipped"],
                chunks=summary["chunks"],
                error_count=len(summary["errors"]),
            )
            return summary

    async def search(
        self,
        *,
        tenant_id: str,
        query: str,
        provider: str | None = None,
        status: str | None = None,
        limit: int = 10,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        with start_span(
            "support.search",
            tenant_id=tenant_id,
            provider=provider or "all",
            status=status or "any",
            limit=limit,
            query_length=len(query or ""),
            lexical_enabled=session is not None,
        ) as span:
            self._require_clients()
            filters: dict[str, Any] = {"tenant_id": tenant_id}
            if provider:
                filters["provider"] = provider
            if status:
                filters["status"] = status

            vector_results: list[dict[str, Any]] = []
            vector_error: Exception | None = None
            try:
                with start_span(
                    "support.search.vector",
                    tenant_id=tenant_id,
                    provider=provider or "all",
                    status=status or "any",
                    limit=limit,
                ) as vector_span:
                    vector = await _embed_client.embed_query(query)
                    results = await _vectordb_client.search(
                        settings.SUPPORT_INDEX_COLLECTION,
                        vector,
                        limit=limit,
                        filters=filters,
                    )
                    vector_results = [self._result_to_response(result) for result in results]
                    set_span_attributes(vector_span, result_count=len(vector_results))
            except Exception as e:
                logger.warning("support index search failed for tenant=%s: %s", tenant_id, e, exc_info=True)
                record_span_error(span, e)
                vector_error = e

            lexical_results: list[dict[str, Any]] = []
            if session is not None:
                with start_span(
                    "support.search.lexical",
                    tenant_id=tenant_id,
                    provider=provider or "all",
                    status=status or "any",
                    limit=max(limit * 2, 10),
                ) as lexical_span:
                    lexical_results = await support_lexical_search(
                        session,
                        tenant_id=tenant_id,
                        query=query,
                        provider=provider,
                        status=status,
                        limit=max(limit * 2, 10),
                    )
                    set_span_attributes(lexical_span, result_count=len(lexical_results))

            if vector_error and not lexical_results:
                raise SupportIndexError("support index is unavailable or has not been initialized") from vector_error

            fused = _fuse_results(vector_results, lexical_results, limit=limit)
            retrieval_sources = sorted({str(result.get("retrieval_source") or "unknown") for result in fused})
            set_span_attributes(
                span,
                vector_result_count=len(vector_results),
                lexical_result_count=len(lexical_results),
                fused_result_count=len(fused),
                retrieval_sources=retrieval_sources,
                vector_failed=vector_error is not None,
            )
            return fused

    async def _index_document(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        document: SupportIndexDocument,
        vector_size: int | None,
    ) -> dict[str, Any]:
        record = await self._get_record(session, tenant_id=tenant_id, document=document)
        if self._is_current(record, document):
            return {"indexed": False, "chunks": 0, "vector_size": vector_size}

        chunks = chunk_text(document.text)
        if not chunks:
            await self._upsert_record(
                session,
                tenant_id=tenant_id,
                document=document,
                chunk_count=0,
            )
            return {"indexed": False, "chunks": 0, "vector_size": vector_size}

        embeddings = await _embed_client.embed_documents(chunks)
        if len(embeddings) != len(chunks):
            raise SupportIndexError(f"embedding count mismatch for {document.provider}:{document.source_id}")
        if not embeddings or not embeddings[0]:
            raise SupportIndexError(f"empty embedding returned for {document.provider}:{document.source_id}")

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
        return {"indexed": True, "chunks": len(chunks), "vector_size": vector_size}

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
            "vector_score": result.get("score"),
            "lexical_score": None,
            "fusion_score": None,
            "retrieval_source": "vector",
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


def _fuse_results(
    vector_results: list[dict[str, Any]],
    lexical_results: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if not lexical_results:
        return vector_results[:limit]
    if not vector_results:
        return lexical_results[:limit]

    fused: dict[tuple[Any, ...], dict[str, Any]] = {}
    for rank, result in enumerate(vector_results, start=1):
        key = _result_key(result)
        item = {**result}
        item["vector_score"] = result.get("score")
        item["fusion_score"] = _rrf(rank)
        item["retrieval_source"] = "vector"
        fused[key] = item

    for rank, result in enumerate(lexical_results, start=1):
        key = _result_key(result)
        lexical_rrf = _rrf(rank)
        existing = fused.get(key)
        if existing:
            existing["lexical_score"] = result.get("lexical_score")
            existing["fusion_score"] = (existing.get("fusion_score") or 0) + lexical_rrf
            existing["retrieval_source"] = "hybrid"
            existing["score"] = _max_score(existing.get("score"), result.get("score"))
        else:
            item = {**result}
            item["vector_score"] = None
            item["fusion_score"] = lexical_rrf
            item["retrieval_source"] = "lexical"
            fused[key] = item

    return sorted(
        fused.values(),
        key=lambda item: (item.get("fusion_score") or 0, item.get("score") or 0),
        reverse=True,
    )[:limit]


def _result_key(result: dict[str, Any]) -> tuple[Any, ...]:
    return (
        result.get("provider"),
        result.get("source_type"),
        result.get("source_id"),
        result.get("chunk_index") or 0,
    )


def _rrf(rank: int, *, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _max_score(left: Any, right: Any) -> Any:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return max(left, right)
    return left if left is not None else right


support_indexer = SupportIndexer()
