"""Bounded orchestration for the authorized resolution ranking stages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from app.clients.base import LLMClient
from app.resolution.llm_reranker import rerank_with_llm
from app.resolution.ranking import (
    RerankItem,
    RerankRequest,
    RerankResult,
    pre_rank_authorized,
)
from app.search.features import RankingFeatures


class RankingStage(str, Enum):
    BASELINE = "baseline"
    FEATURE = "feature"
    LLM = "llm"


@dataclass(frozen=True)
class RankingPolicy:
    """Explicit ranking choice and its operational guardrails."""

    stage: RankingStage = RankingStage.BASELINE
    llm_enabled: bool = True
    kill_switch: bool = False
    timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")


def _baseline(request: RerankRequest) -> RerankResult:
    """Preserve retrieval order while retaining the supplied scores."""
    return RerankResult(
        query_id=request.query_id,
        scope_identity=request.scope_identity,
        items=tuple(
            RerankItem(
                document_id=c.document_id,
                score=c.original_score,
                source_type=c.source_type,
                source_id=c.source_id,
                index_version=c.index_version,
                permission_version=c.permission_version,
                evidence_version=c.evidence_version,
            )
            for c in request.candidates
        ),
    )


def _sort(result: RerankResult) -> RerankResult:
    return result.model_copy(update={"items": tuple(sorted(result.items, key=lambda i: (-i.score, i.document_id)))})


async def rank_authorized(
    request: RerankRequest,
    *,
    policy: RankingPolicy | None = None,
    features_by_document: Mapping[str, RankingFeatures] | None = None,
    client: LLMClient | None = None,
) -> RerankResult:
    """Run one bounded ranking stage; no stage can add or alter candidates."""
    policy = policy or RankingPolicy()
    if policy.kill_switch or policy.stage is RankingStage.BASELINE:
        return _baseline(request).validate_against(request)

    if policy.stage is RankingStage.FEATURE:
        result = pre_rank_authorized(request, features_by_document or {})
        return _sort(result).validate_against(request)

    if client is None or not policy.llm_enabled or policy.timeout_seconds == 0:
        return _baseline(request).validate_against(request)
    try:
        result = await rerank_with_llm(client, request, timeout_seconds=policy.timeout_seconds)
        result.validate_against(request)
        return _sort(result).validate_against(request)
    except Exception:
        return _baseline(request).validate_against(request)


rank_request = rank_authorized

__all__ = ["RankingPolicy", "RankingStage", "rank_authorized", "rank_request"]
