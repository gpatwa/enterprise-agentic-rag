"""Provider-neutral contracts for bounded, authorized reranking."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.search.features import RankingFeatures, default_features


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RerankCandidate(_FrozenModel):
    """A result already authorized by retrieval, with immutable provenance."""

    document_id: str = Field(min_length=1, max_length=255)
    original_rank: int = Field(ge=1)
    original_score: float = Field(ge=0.0, le=1.0)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    index_version: str = Field(min_length=1, max_length=255)
    permission_version: str = Field(min_length=1, max_length=255)
    evidence_version: str = Field(min_length=1, max_length=255)
    evidence_metadata: dict[str, Any] = Field(default_factory=dict)


class RerankRequest(_FrozenModel):
    """Bounded rerank input; candidates must be authorized before construction."""

    query_id: str = Field(min_length=1, max_length=255)
    query: str = Field(min_length=1, max_length=4000)
    scope_identity: str = Field(min_length=1, max_length=255)
    candidates: tuple[RerankCandidate, ...] = Field(min_length=1)
    max_candidates: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_candidates(self) -> RerankRequest:
        ids = [candidate.document_id for candidate in self.candidates]
        if len(self.candidates) > self.max_candidates:
            raise ValueError("candidate set exceeds max_candidates")
        if len(ids) != len(set(ids)):
            raise ValueError("candidate document IDs must be unique")
        ranks = [candidate.original_rank for candidate in self.candidates]
        if len(ranks) != len(set(ranks)):
            raise ValueError("candidate original ranks must be unique")
        return self


class RerankItem(_FrozenModel):
    document_id: str = Field(min_length=1, max_length=255)
    score: float = Field(ge=0.0, le=1.0)
    reason_codes: tuple[str, ...] = ()
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    index_version: str = Field(min_length=1, max_length=255)
    permission_version: str = Field(min_length=1, max_length=255)
    evidence_version: str = Field(min_length=1, max_length=255)


class RerankResult(_FrozenModel):
    """Closed-world rerank output; validate it against its originating request."""

    query_id: str = Field(min_length=1, max_length=255)
    scope_identity: str = Field(min_length=1, max_length=255)
    items: tuple[RerankItem, ...] = Field(min_length=1)

    def validate_against(self, request: RerankRequest) -> RerankResult:
        if self.query_id != request.query_id or self.scope_identity != request.scope_identity:
            raise ValueError("result query or scope identity does not match request")
        expected = {candidate.document_id: candidate for candidate in request.candidates}
        actual = [item.document_id for item in self.items]
        if len(actual) != len(set(actual)):
            raise ValueError("result document IDs must be unique")
        if set(actual) != set(expected):
            raise ValueError("result IDs must exactly match supplied candidates")
        for item in self.items:
            candidate = expected[item.document_id]
            if (item.source_type, item.source_id, item.index_version, item.permission_version, item.evidence_version) != (
                candidate.source_type, candidate.source_id, candidate.index_version,
                candidate.permission_version, candidate.evidence_version,
            ):
                raise ValueError("result cannot alter candidate provenance")
        return self


def pre_rank_authorized(
    request: RerankRequest,
    features_by_document: Mapping[str, RankingFeatures],
    *,
    weights: Mapping[str, float] | None = None,
) -> RerankResult:
    """Apply deterministic feature reranking to an authorized candidate set."""
    active_weights = {
        "recency": 0.1,
        "popularity": 0.1,
        "expertise": 0.1,
        "role_match": 0.05,
        "content_quality": 0.05,
    }
    active_weights.update(weights or {})

    ranked: list[tuple[float, RerankCandidate]] = []
    for candidate in request.candidates:
        feature = features_by_document.get(candidate.document_id, default_features())
        adjustment = sum(getattr(feature, name) * value for name, value in active_weights.items())
        ranked.append((candidate.original_score + adjustment, candidate))

    ranked.sort(key=lambda entry: (-entry[0], entry[1].document_id))
    return RerankResult(
        query_id=request.query_id,
        scope_identity=request.scope_identity,
        items=tuple(
            RerankItem(
                document_id=candidate.document_id,
                score=min(max(score, 0.0), 1.0),
                source_type=candidate.source_type,
                source_id=candidate.source_id,
                index_version=candidate.index_version,
                permission_version=candidate.permission_version,
                evidence_version=candidate.evidence_version,
            )
            for score, candidate in ranked
        ),
    )


__all__ = ["RerankCandidate", "RerankItem", "RerankRequest", "RerankResult", "pre_rank_authorized"]
