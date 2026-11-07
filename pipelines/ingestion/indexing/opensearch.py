"""Writes embedded file chunks to OpenSearch through the API's own document schema and provider (plan option A).

Reusing ``SupportSearchDocument`` and ``OpenSearchProvider`` guarantees schema, mapping and ID parity with the
support search path. It also means the pipeline needs ``services/api`` on ``PYTHONPATH`` and the API's settings
(for example ``OPENSEARCH_*`` and ``PII_REDACTION_ENABLED``) in its environment.

Decisions recorded in docs/RAG_PIPELINE_OPENSEARCH_INDEXER_PLAN.md: tenant-only ACL token, no image content, dimension
checked before any write. The indexer holds only plain config so it pickles into Ray workers; a provider (and its
connection) is created per ``write`` call.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from app.search.models import SearchIndexSpec
from app.search.opensearch import OpenSearchProvider
from app.search.schema import SUPPORT_SEARCH_SCHEMA_VERSION
from app.search.support_mapper import map_file_chunk

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"
PROVIDER_NAME = "ray-ingest"
BULK_SIZE = 200
MAX_RETRY_ROUNDS = 2


class IndexerError(RuntimeError):
    """A write that must fail the job. Messages carry document IDs and codes, never text or credentials."""


@dataclass(frozen=True)
class WriteReport:
    received: int
    indexed: int
    skipped: int


class OpenSearchIndexer:
    def __init__(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        index: str | None = None,
        dimensions: int | None = None,
        embedding_model_version: str | None = None,
        provider_factory: Callable[[], Any] = OpenSearchProvider,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        from app.config import settings

        self.tenant_id = tenant_id
        self.index = index or os.getenv("INGEST_OPENSEARCH_INDEX") or ""
        # Precedence: argument, INGEST_VECTOR_DIMENSIONS, the API's OPENSEARCH_VECTOR_DIMENSIONS (default 768).
        env_dimensions = os.getenv("INGEST_VECTOR_DIMENSIONS")
        self.dimensions = dimensions or (
            int(env_dimensions) if env_dimensions else settings.OPENSEARCH_VECTOR_DIMENSIONS
        )
        self.embedding_model_version = embedding_model_version or settings.OPENSEARCH_EMBEDDING_MODEL_VERSION
        self._provider_factory = provider_factory
        self._sleep = sleep
        if not self.index:
            raise IndexerError("INGEST_OPENSEARCH_INDEX is required: name the index generation to write to")

    def build_documents(self, batch: Iterable[dict[str, Any]]) -> tuple[list[Any], int]:
        """Map rows to documents. Rows without text or a vector, and image rows, are skipped and counted."""
        documents: list[Any] = []
        skipped = 0
        for row in batch:
            vector = row.get("vector")
            text = str(row.get("text") or "").strip()
            if row.get("content_type", "text") != "text" or vector is None or len(vector) == 0 or not text:
                skipped += 1
                continue
            if len(vector) != self.dimensions:
                raise IndexerError(
                    f"vector has {len(vector)} dimensions but the index expects {self.dimensions}; nothing was written "
                    "(set INGEST_VECTOR_DIMENSIONS to the embedding model's size: BGE-M3 is 1024, the Gemini path defaults to 768)"
                )
            meta = dict(row.get("metadata") or {})
            filename = str(meta.get("filename") or "").strip()
            if not filename:
                raise IndexerError("a chunk has no filename in its metadata; nothing was written")
            # The chunk key is the content hash, so the same chunk always gets the same ID (idempotent re-runs).
            chunk_key = f"p{meta.get('page_number', 0)}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
            document = map_file_chunk(
                tenant_id=self.tenant_id,
                provider=PROVIDER_NAME,
                file_id=filename,
                chunk_key=chunk_key,
                title=filename,
                text=text,
                metadata={
                    k: v for k, v in meta.items() if k in {"filename", "page_number", "chunk_index", "chunk_hash"}
                },
                embedding_model_version=self.embedding_model_version,
            )
            documents.append(document.model_copy(update={"vector": tuple(float(x) for x in vector)}))
        return documents, skipped

    def write(self, batch: list[dict[str, Any]]) -> WriteReport:
        documents, skipped = self.build_documents(batch)
        if documents:
            asyncio.run(self._write_async(documents))
        report = WriteReport(received=len(batch), indexed=len(documents), skipped=skipped)
        logger.info("opensearch indexer: %s", report)
        return report

    async def _write_async(self, documents: list[Any]) -> None:
        provider = self._provider_factory()
        await provider.connect()
        try:
            await provider.ensure_index(
                SearchIndexSpec(
                    alias=self.index,
                    generation=self.index,
                    schema_version=SUPPORT_SEARCH_SCHEMA_VERSION,
                    vector_dimensions=self.dimensions,
                    embedding_model_version=self.embedding_model_version,
                )
            )
            pending = documents
            for round_number in range(MAX_RETRY_ROUNDS + 1):
                failures = []
                for start in range(0, len(pending), BULK_SIZE):
                    result = await provider.upsert(pending[start : start + BULK_SIZE], index=self.index)
                    failures.extend(result.errors)
                if not failures:
                    return
                retryable = {error.document_id for error in failures if error.retryable}
                if len(retryable) < len(failures) or round_number == MAX_RETRY_ROUNDS:
                    break
                pending = [d for d in pending if d.document_id in retryable]
                self._sleep(0.5 * (round_number + 1))
            summary = ", ".join(f"{error.document_id}={error.code}" for error in failures[:5])
            raise IndexerError(f"{len(failures)} documents failed to index ({summary})")
        finally:
            await provider.close()
