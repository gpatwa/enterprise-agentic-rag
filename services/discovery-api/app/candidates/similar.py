"""Deterministic item-to-item similarity candidates."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.candidates.contracts import Candidate, CandidateSourceResult, Degradation
from app.domain.models import ExperienceRecord, ImmersiveDiscoveryContext, UserProfile, evaluate_eligibility

_MAX_DIMENSIONS = 4096
_MAX_ITEMS = 10_000
_MAX_K = 100
_SOURCE = "item_similarity"
_SOURCE_VERSION = "imd-item-similarity-v1"


class SimilarityVector(BaseModel):
    """A versioned, non-zero vector associated with one catalog item."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())

    experience_id: str = Field(min_length=1, max_length=255)
    values: tuple[float, ...] = Field(min_length=1, max_length=_MAX_DIMENSIONS)
    model_version: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
    dimensions: int = Field(ge=1, le=_MAX_DIMENSIONS)

    @field_validator("values")
    @classmethod
    def validate_values(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        values = tuple(float(item) for item in value)
        if any(not math.isfinite(item) for item in values):
            raise ValueError("vector values must be finite")
        if not any(values):
            raise ValueError("vector must not be zero")
        return values

    @model_validator(mode="after")
    def validate_dimensions(self) -> "SimilarityVector":
        if len(self.values) != self.dimensions:
            raise ValueError("vector dimensions do not match values")
        return self


class SimilarityConfig(BaseModel):
    """Versioned and bounded knobs for the local similarity source."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_version: str = Field(default=_SOURCE_VERSION, min_length=1, max_length=64)
    max_candidates: int = Field(default=20, ge=1, le=_MAX_K)
    metadata_weight: float = Field(default=0.6, ge=0, le=1, allow_inf_nan=False)
    vector_weight: float = Field(default=0.4, ge=0, le=1, allow_inf_nan=False)
    minimum_score: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_weights(self) -> "SimilarityConfig":
        if self.metadata_weight == 0 and self.vector_weight == 0:
            raise ValueError("at least one similarity weight must be positive")
        return self


class SimilarityEvidence(BaseModel):
    """Redacted explanation for one similar-item candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255)
    metadata_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    vector_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)


class SimilarityResult(BaseModel):
    """Candidate output with bounded, non-sensitive evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_result: CandidateSourceResult
    evidence: tuple[SimilarityEvidence, ...] = Field(max_length=_MAX_K)

    @model_validator(mode="after")
    def validate_alignment(self) -> "SimilarityResult":
        candidate_ids = tuple(item.experience_id for item in self.source_result.candidates)
        evidence_ids = tuple(item.experience_id for item in self.evidence)
        if candidate_ids != evidence_ids:
            raise ValueError("candidate and evidence order must match")
        return self


@dataclass(frozen=True)
class _ScoredItem:
    experience: ExperienceRecord
    score: float
    metadata_score: float
    vector_score: float | None
    reasons: tuple[str, ...]


class ItemSimilarityCandidateSource:
    """Generate deterministic related-item candidates without an external provider."""

    source = _SOURCE

    def __init__(self, config: SimilarityConfig | None = None) -> None:
        self.config = config or SimilarityConfig()

    def retrieve(
        self,
        seed: ExperienceRecord,
        experiences: Iterable[ExperienceRecord],
        context: ImmersiveDiscoveryContext,
        user: UserProfile,
        *,
        vectors: Iterable[SimilarityVector] = (),
        k: int | None = None,
        blocked_ids: tuple[str, ...] = (),
    ) -> SimilarityResult:
        limit = self.config.max_candidates if k is None else k
        if limit < 1 or limit > _MAX_K:
            raise ValueError(f"k must be between 1 and {_MAX_K}")
        tenant_id = context.request_context.tenant_id
        if seed.tenant_id != tenant_id or user.tenant_id != tenant_id:
            raise ValueError("seed, user, and request must share a tenant")
        if not evaluate_eligibility(seed, user, context).eligible:
            return self._result(context, (), (), Degradation.EMPTY)

        catalog = self._catalog(experiences, tenant_id)
        catalog[seed.experience_id] = seed
        vector_map, _ = self._vectors(vectors, tenant_id, catalog)
        seed_vector = vector_map.get(seed.experience_id)
        scored: list[_ScoredItem] = []
        for item_id, item in catalog.items():
            if item_id == seed.experience_id or item_id in blocked_ids or not evaluate_eligibility(item, user, context).eligible:
                continue
            metadata_score = _metadata_similarity(seed, item)
            vector_score = (
                _cosine_similarity(seed_vector.values, vector_map[item_id].values)
                if seed_vector is not None and item_id in vector_map
                else None
            )
            if metadata_score == 0 and vector_score is None:
                continue
            score = self._score(metadata_score, vector_score)
            if score < self.config.minimum_score:
                continue
            reasons = ("metadata_overlap",) if metadata_score > 0 else ()
            if vector_score is not None:
                reasons += ("vector_cosine",)
            scored.append(_ScoredItem(item, score, metadata_score, vector_score, reasons))

        selected = sorted(scored, key=lambda item: (-item.score, item.experience.experience_id))[:limit]
        candidates = tuple(
            Candidate(
                experience_id=item.experience.experience_id,
                tenant_id=tenant_id,
                source=_SOURCE,
                source_version=self.config.source_version,
                score=item.score,
                reason_codes=item.reasons,
            )
            for item in selected
        )
        evidence = tuple(
            SimilarityEvidence(
                experience_id=item.experience.experience_id,
                metadata_score=item.metadata_score,
                vector_score=item.vector_score,
                reason_codes=item.reasons,
            )
            for item in selected
        )
        return self._result(
            context,
            candidates,
            evidence,
            Degradation.OK if candidates else Degradation.EMPTY,
        )

    def _score(self, metadata_score: float, vector_score: float | None) -> float:
        metadata_weight = self.config.metadata_weight if metadata_score > 0 else 0.0
        vector_weight = self.config.vector_weight if vector_score is not None else 0.0
        total = metadata_weight + vector_weight
        if total == 0:
            return 0.0
        return round((metadata_weight * metadata_score + vector_weight * (vector_score or 0.0)) / total, 8)

    @staticmethod
    def _catalog(experiences: Iterable[ExperienceRecord], tenant_id: str) -> dict[str, ExperienceRecord]:
        catalog: dict[str, ExperienceRecord] = {}
        for item in experiences:
            if item.tenant_id != tenant_id:
                continue
            if item.experience_id in catalog:
                raise ValueError("duplicate experience record")
            catalog[item.experience_id] = item
        return catalog

    @staticmethod
    def _vectors(
        vectors: Iterable[SimilarityVector],
        tenant_id: str,
        catalog: dict[str, ExperienceRecord],
    ) -> tuple[dict[str, SimilarityVector], str | None]:
        selected: dict[str, SimilarityVector] = {}
        version: str | None = None
        dimensions: int | None = None
        for vector in vectors:
            item = catalog.get(vector.experience_id)
            if item is None or item.tenant_id != tenant_id:
                continue
            if version is None:
                version, dimensions = vector.model_version, vector.dimensions
            elif vector.model_version != version or vector.dimensions != dimensions:
                raise ValueError("mixed vector versions or dimensions are not allowed")
            if vector.experience_id in selected:
                raise ValueError("duplicate similarity vector")
            selected[vector.experience_id] = vector
        return selected, version

    def _result(
        self,
        context: ImmersiveDiscoveryContext,
        candidates: tuple[Candidate, ...],
        evidence: tuple[SimilarityEvidence, ...],
        degradation: Degradation,
    ) -> SimilarityResult:
        return SimilarityResult(
            source_result=CandidateSourceResult(
                source=_SOURCE,
                source_version=self.config.source_version,
                tenant_id=context.request_context.tenant_id,
                request_id=context.request_context.request_id,
                candidates=candidates,
                degradation=degradation,
                error_code=None,
            ),
            evidence=evidence,
        )


def _metadata_similarity(left: ExperienceRecord, right: ExperienceRecord) -> float:
    genre = _jaccard(left.genres, right.genres)
    theme = _jaccard(left.themes, right.themes)
    mechanic = _jaccard(left.mechanics, right.mechanics)
    return round((0.4 * genre) + (0.3 * theme) + (0.3 * mechanic), 8)


def _jaccard(left: Iterable[object], right: Iterable[object]) -> float:
    left_values, right_values = set(left), set(right)
    union = left_values | right_values
    return len(left_values & right_values) / len(union) if union else 0.0


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have matching dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        raise ValueError("cosine similarity requires non-zero vectors")
    cosine = sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
    return round((cosine + 1.0) / 2.0, 8)
