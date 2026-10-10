from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.search.models import SearchResult, SearchScope


def visible_results(results: Sequence[SearchResult], scope: SearchScope) -> tuple[SearchResult, ...]:
    """Defense-in-depth response filter for provider or mock misconfiguration."""
    return tuple(
        result
        for result in results
        if result.tenant_id == scope.tenant_id
        and f"tenant:{scope.tenant_id}" in result.metadata.get("acl_tokens", [f"tenant:{scope.tenant_id}"])
    )


def safe_audit_attributes(*, mode: str, result_count: int, index_alias: str, index_generation: str) -> Mapping[str, Any]:
    return {
        "mode": mode,
        "result_count": max(result_count, 0),
        "index_alias": index_alias,
        "index_generation": index_generation,
    }
