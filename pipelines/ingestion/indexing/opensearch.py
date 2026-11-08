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
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from pipelines.ingestion.indexing._api_path import ensure_api_importable

ensure_api_importable()

from app.search.models import SearchIndexSpec, SearchScope  # noqa: E402
from app.search.opensearch import OpenSearchProvider  # noqa: E402
from app.search.schema import SUPPORT_SEARCH_SCHEMA_VERSION, ingest_run_tag  # noqa: E402
from app.search.support_mapper import map_file_chunk  # noqa: E402
from app.search.sweep import DEFAULT_MAX_DOCUMENTS  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"
PROVIDER_NAME = "ray-ingest"
BULK_SIZE = 200
MAX_RETRY_ROUNDS = 2


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


def parse_sweep_flag(environ: Mapping[str, str]) -> bool:
    """``INGEST_OPENSEARCH_SWEEP``: off unless explicitly on; an unrecognised value fails the job at start."""
    raw = str(environ.get("INGEST_OPENSEARCH_SWEEP", "")).strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ValueError(f"INGEST_OPENSEARCH_SWEEP must be true or false, got {raw!r}")


class IndexerError(RuntimeError):
    """A write that must fail the job. Messages carry document IDs and codes, never text or credentials."""


@dataclass(frozen=True)
class WriteReport:
    received: int
    indexed: int
    skipped: int


@dataclass(frozen=True)
class SweepReport:
    files: int
    deleted: int


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
        sweep: bool | None = None,
        run_id: str | None = None,
        max_sweep_documents: int | None = None,
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

        # Stale-chunk sweep (off by default). The run id and start time are fixed here, on the driver, so every
        # worker stamps the same values. With the sweep off, documents carry no stamp and nothing is ever deleted.
        self.sweep = parse_sweep_flag(os.environ) if sweep is None else bool(sweep)
        self.run_id = None
        self.run_started_at = None
        self.max_sweep_documents = DEFAULT_MAX_DOCUMENTS
        if self.sweep:
            self.run_id = run_id or os.getenv("INGEST_RUN_ID") or uuid.uuid4().hex
            ingest_run_tag(self.run_id)  # reject an unusable id before any work starts
            self.run_started_at = datetime.now(timezone.utc)
            raw_max = max_sweep_documents or os.getenv("INGEST_OPENSEARCH_SWEEP_MAX_DELETE")
            if raw_max:
                self.max_sweep_documents = int(raw_max)
                if self.max_sweep_documents < 1:
                    raise ValueError("INGEST_OPENSEARCH_SWEEP_MAX_DELETE must be a positive integer")

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
                # The full path identifies the file (chunk IDs and the sweep group by it); the base name is for display.
                file_id=str(meta.get("source_path") or "").strip() or filename,
                chunk_key=chunk_key,
                title=filename,
                text=text,
                metadata={
                    k: v
                    for k, v in meta.items()
                    if k in {"filename", "source_path", "page_number", "chunk_index", "chunk_hash"}
                },
                embedding_model_version=self.embedding_model_version,
                tags=(ingest_run_tag(self.run_id),) if self.sweep else (),
                updated_at=self.run_started_at if self.sweep else None,
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

    def finalize(self) -> SweepReport | None:
        """After a fully successful job: delete this tenant's chunks of the files the run wrote that it did not write.

        Does nothing (and never creates a provider) unless ``INGEST_OPENSEARCH_SWEEP`` is on. Call it from the driver
        only after every sink has written; any error here propagates and fails the job, leaving the new chunks in
        place and the old ones undeleted.
        """
        if not self.sweep:
            return None
        report = asyncio.run(self._sweep_async())
        logger.info("opensearch indexer sweep: %s (run %s)", report, self.run_id)
        return report

    async def _sweep_async(self) -> SweepReport:
        provider = self._provider_factory()
        await provider.connect()
        try:
            stale = await provider.find_stale_file_chunks(
                index=self.index,
                tenant_id=self.tenant_id,
                provider_name=PROVIDER_NAME,
                run_id=self.run_id,
                run_started_at=self.run_started_at,
                max_documents=self.max_sweep_documents,
            )
            if not stale.document_ids:
                return SweepReport(files=len(stale.files), deleted=0)
            # The provider's delete re-reads each document and refuses any that is not this tenant's.
            scope = SearchScope(
                tenant_id=self.tenant_id,
                principal_id="ray-ingest-sweep",
                purpose="ingest-sweep",
                acl_tokens=(f"tenant:{self.tenant_id}",),
            )
            result = await provider.delete(list(stale.document_ids), scope=scope, index=self.index)
            if result.failed:
                summary = ", ".join(f"{error.document_id}={error.code}" for error in result.errors[:5])
                raise IndexerError(f"{result.failed} stale chunks could not be deleted ({summary})")
            return SweepReport(files=len(stale.files), deleted=result.succeeded)
        finally:
            await provider.close()

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
