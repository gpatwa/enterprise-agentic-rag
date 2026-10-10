from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.search.models import SearchRequest, SearchResponse


@dataclass(frozen=True)
class ShadowComparison:
    overlap_at_k: float
    primary_count: int
    shadow_count: int
    rank_deltas: tuple[int, ...]
    primary_latency_ms: float
    shadow_latency_ms: float
    error: str | None = None


async def search_with_shadow(
    primary: Any,
    shadow: Any,
    request: SearchRequest,
    *,
    event_sink: Callable[[str, dict[str, Any]], None] | None = None,
) -> tuple[SearchResponse, ShadowComparison]:
    """Return primary results while making shadow failures non-fatal."""
    primary_start = time.perf_counter()
    shadow_start = time.perf_counter()
    primary_task = asyncio.create_task(primary.search(request))
    shadow_task = asyncio.create_task(shadow.search(request))
    primary_result: SearchResponse
    try:
        primary_result = await primary_task
    except BaseException:
        shadow_task.cancel()
        raise
    primary_latency = (time.perf_counter() - primary_start) * 1000
    try:
        shadow_result = await shadow_task
        shadow_latency = (time.perf_counter() - shadow_start) * 1000
        primary_ids = [result.document_id for result in primary_result.results]
        shadow_ids = [result.document_id for result in shadow_result.results]
        primary_set = set(primary_ids)
        overlap = len(primary_set.intersection(shadow_ids)) / max(len(primary_set), 1)
        shadow_positions = {document_id: rank for rank, document_id in enumerate(shadow_ids, 1)}
        deltas = tuple(
            shadow_positions[document_id] - rank
            for rank, document_id in enumerate(primary_ids, 1)
            if document_id in shadow_positions
        )
        comparison = ShadowComparison(
            overlap_at_k=overlap,
            primary_count=len(primary_ids),
            shadow_count=len(shadow_ids),
            rank_deltas=deltas,
            primary_latency_ms=primary_latency,
            shadow_latency_ms=shadow_latency,
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        shadow_latency = (time.perf_counter() - shadow_start) * 1000
        comparison = ShadowComparison(
            overlap_at_k=0.0,
            primary_count=len(primary_result.results),
            shadow_count=0,
            rank_deltas=(),
            primary_latency_ms=primary_latency,
            shadow_latency_ms=shadow_latency,
            error=type(error).__name__,
        )
    if event_sink:
        event_sink(
            "search.shadow_comparison",
            {
                "overlap_at_k": comparison.overlap_at_k,
                "primary_count": comparison.primary_count,
                "shadow_count": comparison.shadow_count,
                "rank_deltas": comparison.rank_deltas,
                "primary_latency_ms": comparison.primary_latency_ms,
                "shadow_latency_ms": comparison.shadow_latency_ms,
                "error": comparison.error,
            },
        )
    return primary_result, comparison
