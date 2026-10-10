from __future__ import annotations

from collections.abc import Sequence

from app.search.models import SearchResult
from app.search.ranking import rerank_authorized


def similar_candidates(results: Sequence[SearchResult], *, exclude_document_id: str, limit: int = 5) -> tuple[SearchResult, ...]:
    return tuple(result for result in results if result.document_id != exclude_document_id)[:limit]


def next_best_resolution(results: Sequence[SearchResult], *, limit: int = 5) -> tuple[SearchResult, ...]:
    return rerank_authorized(results, {})[:limit]
