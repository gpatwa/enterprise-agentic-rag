"""Queries for the stale file-chunk sweep (docs/RAG_PIPELINE_OPENSEARCH_INDEXER_PLAN.md, 2026-11-06 sweep section).

When an ingested file is edited, the pipeline writes new chunk documents; chunks whose text changed get new document
IDs, so the old ones stay indexed. With sweeping on, every chunk a run writes is stamped with the run (``tags`` gets
``ingest-run:<id>``, ``updated_at`` is the run's start time). Afterwards the sweep finds, for the files the run touched,
chunks that are older than the run and carry another stamp (or none) and deletes them through the provider's
tenant-checked ``delete``.

This module only builds queries and validates inputs; it never talks to a cluster. Every query is pinned to one
tenant, one provider and the ``file_chunk`` source type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.search.schema import ingest_run_tag

FILE_CHUNK_SOURCE_TYPE = "file_chunk"
FILE_FIELD = "title.keyword"  # the pipeline stores the file name as the title
FILES_PER_QUERY = 100
MAX_FILES_PER_SWEEP = 20_000
DEFAULT_MAX_DOCUMENTS = 10_000

_INDEX_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,254}$")


class SweepRefused(ValueError):
    """The sweep declined to delete anything. Nothing was deleted by the call that raised this."""


@dataclass(frozen=True)
class StaleFileChunks:
    document_ids: tuple[str, ...]
    files: tuple[str, ...]


def validate_sweep_inputs(
    *, index: str, tenant_id: str, provider_name: str, run_id: str, run_started_at: datetime, max_documents: int
) -> str:
    """Fail closed on anything ambiguous. Returns the run tag."""
    if not isinstance(index, str) or not _INDEX_NAME.match(index):
        raise SweepRefused("the sweep needs one concrete index name (no wildcards, lists or system indexes)")
    for label, value in (("tenant_id", tenant_id), ("provider_name", provider_name)):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise SweepRefused(f"{label} must be a non-blank string")
    if not isinstance(run_started_at, datetime) or run_started_at.tzinfo is None:
        raise SweepRefused("run_started_at must be a timezone-aware datetime")
    if not isinstance(max_documents, int) or isinstance(max_documents, bool) or max_documents < 1:
        raise SweepRefused("max_documents must be a positive integer")
    try:
        return ingest_run_tag(run_id)
    except ValueError as error:
        raise SweepRefused(str(error)) from error


def _pinned_filters(tenant_id: str, provider_name: str) -> list[dict[str, Any]]:
    return [
        {"term": {"tenant_id": tenant_id}},
        {"term": {"provider": provider_name}},
        {"term": {"source_type": FILE_CHUNK_SOURCE_TYPE}},
    ]


def run_files_query(tenant_id: str, provider_name: str, run_tag: str, after: dict[str, Any] | None) -> dict[str, Any]:
    """Which files did this run write? Counted from the index, so only what really landed is considered."""
    composite: dict[str, Any] = {"size": 1000, "sources": [{"file": {"terms": {"field": FILE_FIELD}}}]}
    if after:
        composite["after"] = after
    return {
        "size": 0,
        "query": {"bool": {"filter": [*_pinned_filters(tenant_id, provider_name), {"term": {"tags": run_tag}}]}},
        "aggs": {"files": {"composite": composite}},
    }


def stale_chunks_query(
    tenant_id: str,
    provider_name: str,
    run_tag: str,
    run_started_at: datetime,
    files: list[str],
    *,
    page_size: int,
    search_after: list[Any] | None,
) -> dict[str, Any]:
    started = run_started_at.astimezone(timezone.utc).isoformat()
    body: dict[str, Any] = {
        "size": page_size,
        "track_total_hits": False,
        "_source": ["document_id", "tenant_id", "provider", "source_type", "tags"],
        "sort": [{"document_id": "asc"}],
        "query": {
            "bool": {
                "filter": [*_pinned_filters(tenant_id, provider_name), {"terms": {FILE_FIELD: files}}],
                # Not written by this run ...
                "must_not": [{"term": {"tags": run_tag}}],
                # ... and older than it. A chunk written after this run began (a second job for the same file)
                # is never ours to delete. Chunks that predate run stamps have no updated_at and count as older.
                "should": [
                    {"range": {"updated_at": {"lt": started}}},
                    {"bool": {"must_not": [{"exists": {"field": "updated_at"}}]}},
                ],
                "minimum_should_match": 1,
            }
        },
    }
    if search_after is not None:
        body["search_after"] = search_after
    return body


def check_hit(source: Any, *, tenant_id: str, provider_name: str, run_tag: str) -> str:
    """Re-check one returned hit against the pins, whatever the query said. Returns its document id."""
    if not isinstance(source, dict):
        raise SweepRefused("the cluster returned a hit without a source; refusing to delete")
    tags = source.get("tags") or []
    document_id = source.get("document_id")
    if (
        source.get("tenant_id") != tenant_id
        or source.get("provider") != provider_name
        or source.get("source_type") != FILE_CHUNK_SOURCE_TYPE
        or run_tag in tags
        or not isinstance(document_id, str)
        or not document_id
    ):
        raise SweepRefused(
            "the cluster returned a document outside the sweep's tenant, provider or run; refusing to delete"
        )
    return document_id
