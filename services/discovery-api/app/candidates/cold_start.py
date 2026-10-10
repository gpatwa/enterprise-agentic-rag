"""Deterministic user and item cold-start candidates."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.candidates.contracts import Candidate, CandidateSourceResult, Degradation
from app.domain.models import (
    ExperienceRecord,
    HistoryLength,
    ImmersiveDiscoveryContext,
    UserProfile,
    evaluate_eligibility,
)

_MAX_CANDIDATES = 1_000
_SOURCE = "cold_start"
_SOURCE_VERSION = "imd-cold-start-v1"


class ColdStartConfig(BaseModel):
    """Bounded knobs for cold-start exploration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_version: str = Field(default=_SOURCE_VERSION, min_length=1, max_length=64)
    max_candidates: int = Field(default=20, ge=1, le=_MAX_CANDIDATES)
    max_exploration_candidates: int = Field(default=20, ge=1, le=_MAX_CANDIDATES)
    max_per_creator: int = Field(default=2, ge=1, le=100)
    minimum_quality: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)


class ColdStartEvidence(BaseModel):
    """Redacted evidence for a cold-start candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255)
    cold_start_state: str = Field(min_length=1, max_length=32)
    quality_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    contextual_prior: float = Field(ge=0, le=1, allow_inf_nan=False)
    exploration_rank: int = Field(ge=0, le=_MAX_CANDIDATES)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)


class ColdStartResult(BaseModel):
    """Bounded candidate output and non-sensitive explanation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_result: CandidateSourceResult
    evidence: tuple[ColdStartEvidence, ...] = Field(max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_alignment(self) -> "ColdStartResult":
        candidate_ids = tuple(item.experience_id for item in self.source_result.candidates)
        evidence_ids = tuple(item.experience_id for item in self.evidence)
        if candidate_ids != evidence_ids:
            raise ValueError("candidate and evidence order must match")
        return self


@dataclass(frozen=True)
class _ScoredCandidate:
    experience: ExperienceRecord
    score: float
    quality: float
    prior: float
    state: str
    digest: str


class ColdStartCandidateSource:
    """Select safe, bounded exploration candidates without model calls."""

    source = _SOURCE

    def __init__(self, config: ColdStartConfig | None = None) -> None:
        self.config = config or ColdStartConfig()

    def retrieve(
        self,
        experiences: Iterable[ExperienceRecord],
        context: ImmersiveDiscoveryContext,
        user: UserProfile,
        *,
        item_history: Mapping[str, int] | None = None,
        seed: str = "cold-start",
        blocked_ids: tuple[str, ...] = (),
        k: int | None = None,
    ) -> ColdStartResult:
        limit = self.config.max_candidates if k is None else k
        if not 1 <= limit <= _MAX_CANDIDATES:
            raise ValueError("k is out of bounds")
        tenant_id = context.request_context.tenant_id
        if user.tenant_id != tenant_id:
            raise ValueError("user and request must share a tenant")
        if not user.synthetic:
            raise ValueError("cold-start policy accepts synthetic users only")
        history = self._history(item_history)
        catalog = self._catalog(experiences, tenant_id)
        new_user = user.history_length is HistoryLength.NONE
        scored: list[_ScoredCandidate] = []
        for experience in catalog.values():
            if experience.experience_id in blocked_ids:
                continue
            new_item = self._is_new_item(experience, history)
            if not new_user and not new_item:
                continue
            decision = evaluate_eligibility(experience, user, context)
            if not decision.eligible:
                continue
            quality = self._quality(experience)
            if quality < self.config.minimum_quality:
                continue
            prior = self._prior(experience, user, context)
            state = "new_user_and_new_item" if new_user and new_item else ("new_user" if new_user else "new_item")
            digest = hashlib.sha256(f"{seed}:{tenant_id}:{experience.experience_id}".encode("utf-8")).hexdigest()
            scored.append(_ScoredCandidate(experience, 0.65 * prior + 0.35 * quality, quality, prior, state, digest))

        ordered = sorted(scored, key=lambda item: (-item.score, item.digest, item.experience.experience_id))
        chosen: list[_ScoredCandidate] = []
        creator_counts: dict[str, int] = {}
        for item in ordered:
            if len(chosen) >= min(limit, self.config.max_exploration_candidates):
                break
            count = creator_counts.get(item.experience.creator_id, 0)
            if count >= self.config.max_per_creator:
                continue
            creator_counts[item.experience.creator_id] = count + 1
            chosen.append(item)

        candidates = tuple(
            Candidate(
                experience_id=item.experience.experience_id,
                tenant_id=tenant_id,
                source=_SOURCE,
                source_version=self.config.source_version,
                score=item.score,
                reason_codes=self._reasons(item),
            )
            for item in chosen
        )
        evidence = tuple(
            ColdStartEvidence(
                experience_id=item.experience.experience_id,
                cold_start_state=item.state,
                quality_score=item.quality,
                contextual_prior=item.prior,
                exploration_rank=index,
                reason_codes=self._reasons(item),
            )
            for index, item in enumerate(chosen, start=1)
        )
        return ColdStartResult(
            source_result=CandidateSourceResult(
                source=_SOURCE,
                source_version=self.config.source_version,
                tenant_id=tenant_id,
                request_id=context.request_context.request_id,
                candidates=candidates,
                degradation=Degradation.OK if candidates else Degradation.EMPTY,
            ),
            evidence=evidence,
        )

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

    @staticmethod
    def _history(item_history: Mapping[str, int] | None) -> dict[str, int]:
        if item_history is None:
            return {}
        if len(item_history) > _MAX_CANDIDATES:
            raise ValueError("item history exceeds configured bound")
        result: dict[str, int] = {}
        for experience_id, count in item_history.items():
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("item history counts must be non-negative integers")
            result[experience_id] = count
        return result

    @staticmethod
    def _is_new_item(experience: ExperienceRecord, history: Mapping[str, int]) -> bool:
        if experience.experience_id in history:
            return history[experience.experience_id] == 0
        return experience.signals is None

    @staticmethod
    def _quality(experience: ExperienceRecord) -> float:
        if experience.signals is None:
            return 0.5
        if experience.signals.derived_score is not None:
            return _bounded(experience.signals.derived_score)
        return 1.0 if experience.signals.quality_band.value == "high" else 0.6

    @staticmethod
    def _prior(experience: ExperienceRecord, user: UserProfile, context: ImmersiveDiscoveryContext) -> float:
        preference_genres = set(user.preferences.genres) | set(context.filters.genres)
        preference_themes = set(user.preferences.themes) | set(context.filters.themes)
        genre_score = len(preference_genres & set(experience.genres)) / len(preference_genres) if preference_genres else 0.5
        theme_score = len(preference_themes & set(experience.themes)) / len(preference_themes) if preference_themes else 0.5
        return _bounded(0.6 * genre_score + 0.4 * theme_score)

    @staticmethod
    def _reasons(item: _ScoredCandidate) -> tuple[str, ...]:
        reasons = [item.state, "contextual_prior", "quality_gate", "bounded_exploration", "creator_cap"]
        return tuple(reasons)


def _bounded(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("quality values must be finite")
    return max(0.0, min(1.0, value))
