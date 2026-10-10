from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.search.backfill import iter_source_documents
from app.search.models import BulkWriteResult, SearchIndexSpec
from app.search.reconcile import ReconciliationReport, SearchReconciler
from app.search.schema import SUPPORT_SEARCH_SCHEMA_VERSION


@dataclass
class ReindexResult:
    alias: str
    generation: str
    documents_written: int
    report: ReconciliationReport
    swapped: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "generation": self.generation,
            "documents_written": self.documents_written,
            "swapped": self.swapped,
            "reconciliation": self.report.as_dict(),
        }


class SearchReindexError(RuntimeError):
    pass


class SearchReindexCoordinator:
    """Build a new generation and atomically swap only after reconciliation."""

    def __init__(self, reconciler: SearchReconciler | None = None) -> None:
        self.reconciler = reconciler or SearchReconciler()

    async def run(
        self,
        session: AsyncSession,
        *,
        tenant_id: str | None,
        provider_name: str,
        provider: Any,
        alias: str | None = None,
        generation: str | None = None,
        vector_dimensions: int | None = None,
        embedding_model_version: str | None = None,
        batch_size: int = 100,
        max_mismatches: int = 0,
    ) -> ReindexResult:
        target_alias = (alias or settings.OPENSEARCH_INDEX_ALIAS).strip()
        target_generation = generation or _generation_name(target_alias)
        spec = SearchIndexSpec(
            alias=target_alias,
            generation=target_generation,
            schema_version=SUPPORT_SEARCH_SCHEMA_VERSION,
            vector_dimensions=vector_dimensions or settings.OPENSEARCH_VECTOR_DIMENSIONS,
            embedding_model_version=(
                embedding_model_version or settings.OPENSEARCH_EMBEDDING_MODEL_VERSION
            ),
        )
        await provider.ensure_index(spec)

        documents_written = 0
        batch = []
        async for document in _source_documents(
            session,
            tenant_id=tenant_id,
            provider_name=provider_name,
        ):
            batch.append(document)
            if len(batch) >= min(max(batch_size, 1), 500):
                documents_written += await _write_batch(provider, batch, target_generation)
                batch = []
        if batch:
            documents_written += await _write_batch(provider, batch, target_generation)

        report = await self.reconciler.reconcile(
            session,
            tenant_id=tenant_id,
            provider=provider,
            index=target_generation,
            source_provider=provider_name,
        )
        allowed_mismatches = max(max_mismatches, 0)
        swapped = report.mismatch_count <= allowed_mismatches
        if swapped:
            await provider.activate_alias(target_alias, target_generation)
        return ReindexResult(
            alias=target_alias,
            generation=target_generation,
            documents_written=documents_written,
            report=report,
            swapped=swapped,
        )


async def _source_documents(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider_name: str,
):
    async for document in iter_source_documents(
        session,
        tenant_id=tenant_id,
        provider=provider_name,
    ):
        yield document


async def _write_batch(provider: Any, documents: list[Any], index: str) -> int:
    result: BulkWriteResult = await provider.upsert(documents, index=index)
    if result.failed:
        first = result.errors[0]
        raise SearchReindexError(f"{first.code}: {first.message}")
    return result.succeeded


def _generation_name(alias: str) -> str:
    safe_alias = re.sub(r"[^a-zA-Z0-9._-]+", "-", alias).strip("-") or "search"
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{safe_alias}-{timestamp}-{uuid.uuid4().hex[:8]}"


search_reindex_coordinator = SearchReindexCoordinator()
