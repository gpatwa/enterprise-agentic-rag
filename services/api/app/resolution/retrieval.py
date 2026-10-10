"""Bounded, provider-neutral retrieval for a resolution search plan."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.resolution.models import QueryMode, SearchPlan
from app.search.models import RankingExplanation, SearchMode, SearchRequest, SearchResult


def _search_mode(mode: QueryMode) -> SearchMode:
    return {
        QueryMode.EXACT: SearchMode.LEXICAL,
        QueryMode.LEXICAL: SearchMode.LEXICAL,
        QueryMode.SEMANTIC: SearchMode.VECTOR,
        QueryMode.HYBRID: SearchMode.HYBRID,
    }[mode]


class RetrievalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RetrievalProvenance(RetrievalModel):
    document_id: str = Field(min_length=1, max_length=255)
    query: str = Field(min_length=1, max_length=1000)
    mode: SearchMode
    score: float = Field(ge=0.0)
    rank: int = Field(ge=1)
    explanation: RankingExplanation | None = None


class RetrievalFailure(RetrievalModel):
    variant_index: int = Field(ge=0)
    query: str = Field(min_length=1, max_length=1000)
    mode: QueryMode
    error_type: str = Field(min_length=1, max_length=128)


class RetrievalResult(RetrievalModel):
    results: tuple[SearchResult, ...] = ()
    provenance: tuple[RetrievalProvenance, ...] = ()
    executed_variants: int = Field(ge=0)
    failures: tuple[RetrievalFailure, ...] = ()
    partial: bool = False


class MultiQueryRetriever:
    def __init__(self, search_service: Any, *, per_query_result_limit: int = 10, total_result_limit: int = 10) -> None:
        if not 1 <= per_query_result_limit <= 100 or not 1 <= total_result_limit <= 100:
            raise ValueError("result limits must be between 1 and 100")
        self.search_service = search_service
        self.per_query_result_limit = per_query_result_limit
        self.total_result_limit = total_result_limit

    async def retrieve(self, plan: SearchPlan) -> RetrievalResult:
        selected: dict[str, tuple[SearchResult, RetrievalProvenance]] = {}
        failures: list[RetrievalFailure] = []
        for index, variant in enumerate(plan.variants):
            request = SearchRequest(
                text=variant.query,
                scope=plan.scope,
                mode=_search_mode(variant.mode),
                limit=self.per_query_result_limit,
            )
            try:
                response = await self.search_service.search(request)
            except Exception as error:
                failures.append(RetrievalFailure(
                    variant_index=index, query=variant.query, mode=variant.mode,
                    error_type=type(error).__name__,
                ))
                continue
            for result in response.results[: self.per_query_result_limit]:
                if result.tenant_id != plan.scope.tenant_id:
                    failures.append(RetrievalFailure(
                        variant_index=index,
                        query=variant.query,
                        mode=variant.mode,
                        error_type="tenant_scope_mismatch",
                    ))
                    continue
                provenance = RetrievalProvenance(
                    document_id=result.document_id, query=variant.query,
                    mode=request.mode, score=result.score, rank=result.rank,
                    explanation=result.explanation,
                )
                current = selected.get(result.document_id)
                if current is None or (result.score, -result.rank) > (current[0].score, -current[0].rank):
                    selected[result.document_id] = (result, provenance)

        ordered = sorted(selected.values(), key=lambda item: (-item[0].score, item[0].rank, item[0].document_id))
        bounded = ordered[: self.total_result_limit]
        return RetrievalResult(
            results=tuple(item[0] for item in bounded),
            provenance=tuple(item[1] for item in bounded),
            executed_variants=len(plan.variants),
            failures=tuple(failures),
            partial=bool(failures),
        )

__all__ = ["MultiQueryRetriever", "RetrievalFailure", "RetrievalProvenance", "RetrievalResult"]
