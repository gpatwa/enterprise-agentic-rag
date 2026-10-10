"""Deterministic trending candidates from point-in-time feature snapshots."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.candidates.contracts import Candidate, CandidateSourceResult, Degradation
from app.domain.models import (
    ExperienceRecord,
    ImmersiveDiscoveryContext,
    UserProfile,
    evaluate_eligibility,
)
from app.features.materialization import FeatureKind, FeatureRecord

_MAX_CANDIDATES = 1_000
_SOURCE = "trending"
_SOURCE_VERSION = "imd-trending-v1"


class TrendingConfig(BaseModel):
    """Versioned, bounded knobs for the local trending source."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    feature_version: str = Field(default="v1", min_length=1, max_length=128)
    source_version: str = Field(default=_SOURCE_VERSION, min_length=1, max_length=64)
    max_candidates: int = Field(default=50, ge=1, le=_MAX_CANDIDATES)
    max_feature_age_seconds: float = Field(default=86_400.0, ge=0, le=31_536_000, allow_inf_nan=False)
    half_life_seconds: float = Field(default=86_400.0, gt=0, le=31_536_000, allow_inf_nan=False)
    minimum_quality: float = Field(default=0.20, ge=0, le=1, allow_inf_nan=False)
    small_item_prior_impressions: float = Field(default=20.0, ge=0, le=100_000, allow_inf_nan=False)


class TrendingEvidence(BaseModel):
    """Redacted, deterministic explanation for one trending candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255)
    quality_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    popularity_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    freshness_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    impressions: int = Field(ge=0)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)


class TrendingResult(BaseModel):
    """Candidate output and bounded evidence for one request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_result: CandidateSourceResult
    evidence: tuple[TrendingEvidence, ...] = Field(max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_alignment(self) -> "TrendingResult":
        candidate_ids = tuple(item.experience_id for item in self.source_result.candidates)
        evidence_ids = tuple(item.experience_id for item in self.evidence)
        if candidate_ids != evidence_ids:
            raise ValueError("candidate and evidence order must match")
        return self


class _ScoredItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience: ExperienceRecord
    record: FeatureRecord
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    quality: float = Field(ge=0, le=1, allow_inf_nan=False)
    popularity: float = Field(ge=0, le=1, allow_inf_nan=False)
    freshness: float = Field(ge=0, le=1, allow_inf_nan=False)
    impressions: int = Field(ge=0)
    reasons: tuple[str, ...] = Field(min_length=1, max_length=8)


class TrendingCandidateSource:
    """Generate eligible trending candidates without contacting a provider."""

    source = _SOURCE

    def __init__(self, config: TrendingConfig | None = None) -> None:
        self.config = config or TrendingConfig()

    def retrieve(
        self,
        features: Iterable[FeatureRecord],
        experiences: Iterable[ExperienceRecord],
        context: ImmersiveDiscoveryContext,
        user: UserProfile,
        *,
        as_of: datetime,
        request_id: str | None = None,
    ) -> TrendingResult:
        _require_aware(as_of, "as_of")
        if user.tenant_id != context.request_context.tenant_id:
            raise ValueError("user and request tenant must match")
        request = request_id or context.request_context.request_id
        records = self._validate_features(features, as_of, context.request_context.tenant_id)
        catalog = self._catalog(experiences, context.request_context.tenant_id)
        scored = tuple(
            scored_item
            for record in records
            if record.subject_id in catalog
            and (scored_item := self._score(record, catalog[record.subject_id], as_of)) is not None
            and evaluate_eligibility(catalog[record.subject_id], user, context).eligible
        )
        ordered = tuple(sorted(scored, key=lambda item: (-item.score, item.experience.experience_id)))
        selected = ordered[: self.config.max_candidates]
        candidates = tuple(
            Candidate(
                experience_id=item.experience.experience_id,
                tenant_id=item.experience.tenant_id,
                source=_SOURCE,
                source_version=self.config.source_version,
                score=item.score,
                reason_codes=item.reasons,
            )
            for item in selected
        )
        evidence = tuple(
            TrendingEvidence(
                experience_id=item.experience.experience_id,
                quality_score=item.quality,
                popularity_score=item.popularity,
                freshness_score=item.freshness,
                impressions=item.impressions,
                reason_codes=item.reasons,
            )
            for item in selected
        )
        result = CandidateSourceResult(
            source=_SOURCE,
            source_version=self.config.source_version,
            tenant_id=context.request_context.tenant_id,
            request_id=request,
            candidates=candidates,
            degradation=Degradation.OK if candidates else Degradation.EMPTY,
        )
        return TrendingResult(source_result=result, evidence=evidence)

    def _validate_features(self, features: Iterable[FeatureRecord], as_of: datetime, tenant_id: str) -> tuple[FeatureRecord, ...]:
        selected: list[FeatureRecord] = []
        seen: set[tuple[str, str]] = set()
        for record in features:
            if record.subject_type is not FeatureKind.POPULARITY:
                continue
            if record.tenant_id != tenant_id:
                continue
            if record.feature_version != self.config.feature_version:
                raise ValueError("feature version does not match trending configuration")
            if record.as_of > as_of:
                raise ValueError("feature snapshot is after requested as_of")
            if record.feature_age_seconds > self.config.max_feature_age_seconds:
                raise ValueError("feature snapshot is stale")
            if record.source_watermark > record.as_of:
                raise ValueError("feature watermark is after feature snapshot")
            key = (record.tenant_id, record.subject_id)
            if key in seen:
                raise ValueError("duplicate popularity feature record")
            seen.add(key)
            selected.append(record)
        return tuple(selected)

    @staticmethod
    def _catalog(experiences: Iterable[ExperienceRecord], tenant_id: str) -> dict[str, ExperienceRecord]:
        catalog: dict[str, ExperienceRecord] = {}
        for experience in experiences:
            if experience.tenant_id != tenant_id:
                continue
            if experience.experience_id in catalog:
                raise ValueError("duplicate experience record")
            catalog[experience.experience_id] = experience
        return catalog

    def _score(self, record: FeatureRecord, experience: ExperienceRecord, as_of: datetime) -> _ScoredItem | None:
        values = record.values
        impressions = _whole_number(values.get("impressions", 0.0), "impressions")
        qualified_plays = _whole_number(values.get("qualified_plays", 0.0), "qualified_plays")
        raw_quality = _bounded(values.get("quality_score", values.get("qualified_play_rate", 0.0)))
        prior = self.config.small_item_prior_impressions
        quality = _bounded((qualified_plays + raw_quality * prior) / (impressions + prior)) if prior else raw_quality
        if quality < self.config.minimum_quality:
            return None
        age = max(0.0, (as_of - record.as_of).total_seconds())
        freshness = math.exp(-math.log(2.0) * age / self.config.half_life_seconds)
        # Smooth volume as well as rate so one early success cannot look like
        # an established trend while still allowing small items to compete.
        popularity = _bounded(
            math.log1p(qualified_plays) / math.log1p(max(impressions + self.config.small_item_prior_impressions, 1.0))
        )
        score = _bounded(0.55 * quality + 0.30 * popularity + 0.15 * freshness)
        reasons = ("quality_gate", "time_decay", "small_item_normalization")
        if freshness >= 0.5:
            reasons += ("fresh",)
        if impressions < self.config.small_item_prior_impressions:
            reasons += ("small_item",)
        return _ScoredItem(experience=experience, record=record, score=score, quality=quality, popularity=popularity, freshness=freshness, impressions=impressions, reasons=reasons)


def _bounded(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("feature values must be finite")
    return max(0.0, min(1.0, value))


def _whole_number(value: float, field_name: str) -> int:
    if not math.isfinite(value) or value < 0 or value != int(value):
        raise ValueError(f"{field_name} must be a non-negative whole number")
    return int(value)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
