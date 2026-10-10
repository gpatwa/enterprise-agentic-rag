"""Deterministic, closed-world pre-ranking for immersive discovery."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ranking.contracts import FeatureKind, FeatureSet, RankingContext

_MAX_CANDIDATES = 500
_MAX_REASONS = 8
_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_NAME = r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$"
_DEFAULT_WEIGHTS = {
    "quality": 0.35,
    "popularity": 0.20,
    "freshness": 0.15,
    "affinity": 0.20,
    "novelty": 0.10,
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PreRankCandidate(_FrozenModel):
    """Candidate provenance that a pre-ranker may carry but never change."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    original_rank: int = Field(ge=1, le=_MAX_CANDIDATES)
    base_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)
    eligible: Literal[True] = True

    @model_validator(mode="after")
    def validate_reasons(self) -> "PreRankCandidate":
        if any(not reason or len(reason) > 64 for reason in self.reason_codes + self.evidence):
            raise ValueError("candidate evidence and reason codes must be bounded")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("candidate reason codes must be unique")
        return self


class PreRankConfig(_FrozenModel):
    """Versioned, bounded feature weights for one pre-ranking call."""

    ranking_version: str = Field(default="pre-rank-v1", min_length=1, max_length=128, pattern=_VERSION)
    feature_weights: Mapping[str, float] = Field(default_factory=lambda: _DEFAULT_WEIGHTS.copy())
    limit: int = Field(default=50, ge=1, le=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_weights(self) -> "PreRankConfig":
        if not self.feature_weights:
            raise ValueError("at least one allowlisted feature weight is required")
        for name, weight in self.feature_weights.items():
            if not isinstance(name, str) or not name or not re.fullmatch(_NAME, name):
                raise ValueError("feature names must be valid allowlisted names")
            if not isfinite(weight) or weight < 0 or weight > 1:
                raise ValueError("feature weights must be finite and between 0 and 1")
        return self


class PreRankItem(_FrozenModel):
    """A reordered candidate with redacted scoring evidence."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    original_rank: int = Field(ge=1, le=_MAX_CANDIDATES)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)
    eligible: Literal[True] = True


class PreRankResult(_FrozenModel):
    """Closed-world pre-rank output and the contract version used."""

    ranking_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    items: tuple[PreRankItem, ...] = Field(max_length=_MAX_CANDIDATES)
    used_history: bool

    def validate_against(
        self,
        candidates: Sequence[PreRankCandidate],
        *,
        ranking_version: str,
    ) -> "PreRankResult":
        if self.ranking_version != ranking_version:
            raise ValueError("result ranking version does not match request")
        supplied = {candidate.candidate_id: candidate for candidate in candidates}
        actual = [item.candidate_id for item in self.items]
        if len(actual) != len(set(actual)):
            raise ValueError("result candidate IDs must be unique")
        if not set(actual).issubset(supplied):
            raise ValueError("result candidate is outside supplied batch")
        for item in self.items:
            candidate = supplied[item.candidate_id]
            if (item.source, item.original_rank, item.reason_codes, item.evidence, item.eligible) != (
                candidate.source,
                candidate.original_rank,
                candidate.reason_codes,
                candidate.evidence,
                candidate.eligible,
            ):
                raise ValueError("pre-rank cannot alter candidate provenance or eligibility")
        return self


class DeterministicPreRanker:
    """Score eligible candidates using only frozen numeric feature values."""

    def __init__(self, config: PreRankConfig | None = None) -> None:
        self.config = config or PreRankConfig()

    def rank(
        self,
        context: RankingContext,
        candidates: Sequence[PreRankCandidate],
    ) -> PreRankResult:
        supplied = tuple(candidates)
        if not supplied:
            raise ValueError("candidate batch cannot be empty")
        if len(supplied) > _MAX_CANDIDATES:
            raise ValueError("candidate batch exceeds bound")
        self._validate_batch(context, supplied)
        feature_sets = {candidate.subject_id: candidate for candidate in context.candidates}
        used_history = context.user is not None and any(
            feature.name.startswith("history.") or feature.name in {"plays", "saves", "dismissals"}
            for feature in context.user.features
        )
        scored = []
        for candidate in supplied:
            features = feature_sets[candidate.candidate_id]
            feature_score = self._feature_score(features)
            score = candidate.base_score if not used_history else min(1.0, max(0.0, candidate.base_score + feature_score))
            scored.append((score, candidate))
        scored.sort(key=lambda entry: (-entry[0], entry[1].original_rank, entry[1].candidate_id))
        items = tuple(
            PreRankItem(
                candidate_id=candidate.candidate_id,
                source=candidate.source,
                score=score,
                original_rank=candidate.original_rank,
                reason_codes=candidate.reason_codes,
                evidence=candidate.evidence,
            )
            for score, candidate in scored[: self.config.limit]
        )
        return PreRankResult(
            ranking_version=self.config.ranking_version,
            items=items,
            used_history=bool(used_history),
        )

    def _feature_score(self, feature_set: FeatureSet) -> float:
        total = 0.0
        for feature in feature_set.features:
            if feature.name not in self.config.feature_weights:
                raise ValueError(f"unknown ranking feature: {feature.name}")
            if feature.missing_reason is not None:
                continue
            if feature.kind == "numeric":
                value = feature.numeric_value
            elif feature.kind == "boolean":
                value = 1.0 if feature.boolean_value else 0.0
            else:
                raise ValueError(f"categorical feature cannot be pre-ranked: {feature.name}")
            if value is None or not isfinite(value):
                raise ValueError("ranking features must be finite")
            total += value * self.config.feature_weights[feature.name]
        return total

    def _validate_batch(self, context: RankingContext, candidates: tuple[PreRankCandidate, ...]) -> None:
        if any(not candidate.eligible for candidate in candidates):
            raise ValueError("pre-ranker accepts eligible candidates only")
        ids = [candidate.candidate_id for candidate in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        supplied_ids = {candidate.subject_id for candidate in context.candidates}
        if not set(ids).issubset(supplied_ids):
            raise ValueError("candidate is outside supplied ranking batch")
        if context.ranking_version != self.config.ranking_version:
            raise ValueError("ranking version does not match pre-rank configuration")
        if context.context.feature_kind is not FeatureKind.CONTEXT:
            raise ValueError("ranking context must contain context features")


def pre_rank_candidates(
    context: RankingContext,
    candidates: Sequence[PreRankCandidate],
    *,
    config: PreRankConfig | None = None,
) -> PreRankResult:
    """Convenience entry point for deterministic pre-ranking."""
    return DeterministicPreRanker(config).rank(context, candidates)


__all__ = [
    "DeterministicPreRanker",
    "PreRankCandidate",
    "PreRankConfig",
    "PreRankItem",
    "PreRankResult",
    "pre_rank_candidates",
]
