"""Strict, bounded fakes for immersive discovery contract tests."""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import (
    ExperienceRecord,
    ImmersiveDiscoveryContext,
    UserProfile,
    evaluate_eligibility,
)


class FakeMode(str, Enum):
    NORMAL = "normal"
    FAILURE = "failure"
    TIMEOUT = "timeout"


class FakeProviderError(RuntimeError):
    """Deterministic provider failure used by fake implementations."""


class FakeTimeoutError(TimeoutError):
    """Deterministic timeout used by fake implementations."""


class _FakeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FakeConfig(_FakeModel):
    mode: FakeMode = FakeMode.NORMAL
    max_calls: int = Field(default=64, ge=1, le=1_000)
    max_items: int = Field(default=100, ge=1, le=1_000)


class TraceEntry(_FakeModel):
    """A bounded trace that stores digests rather than caller identifiers."""

    operation: str = Field(min_length=1, max_length=64)
    tenant_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    principal_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    item_digests: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    item_count: int = Field(ge=0, le=1_000)


class FakeCandidate(_FakeModel):
    experience_id: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=64)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_text(self) -> "FakeCandidate":
        if not self.experience_id.strip() or not self.source.strip():
            raise ValueError("candidate identifiers must be non-empty")
        return self


class FakeFeature(_FakeModel):
    experience_id: str = Field(min_length=1, max_length=255)
    values: tuple[tuple[str, float], ...] = Field(default_factory=tuple, max_length=32)

    @model_validator(mode="after")
    def validate_values(self) -> "FakeFeature":
        if not self.experience_id.strip():
            raise ValueError("experience_id must be non-empty")
        if any(not name.strip() or not 0 <= value <= 1 for name, value in self.values):
            raise ValueError("feature names must be non-empty and values must be between 0 and 1")
        if len({name for name, _ in self.values}) != len(self.values):
            raise ValueError("feature names must be unique")
        return self


class FakeRankedCandidate(_FakeModel):
    experience_id: str = Field(min_length=1, max_length=255)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    rank: int = Field(ge=1, le=1_000)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _FakeProvider:
    def __init__(self, config: FakeConfig | None = None) -> None:
        self.config = config or FakeConfig()
        self._trace: list[TraceEntry] = []

    @property
    def trace(self) -> tuple[TraceEntry, ...]:
        return tuple(self._trace)

    def _record(
        self,
        operation: str,
        context: ImmersiveDiscoveryContext,
        item_ids: Iterable[str] = (),
    ) -> None:
        if len(self._trace) >= self.config.max_calls:
            raise FakeProviderError("fake call limit exceeded")
        bounded_ids = tuple(item_ids)
        if len(bounded_ids) > self.config.max_items:
            raise FakeProviderError("fake item limit exceeded")
        request = context.request_context
        self._trace.append(
            TraceEntry(
                operation=operation,
                tenant_digest=_digest(request.tenant_id),
                principal_digest=_digest(request.principal_id),
                request_digest=_digest(request.request_id),
                item_digests=tuple(_digest(item_id) for item_id in bounded_ids),
                item_count=len(bounded_ids),
            )
        )
        if self.config.mode is FakeMode.FAILURE:
            raise FakeProviderError(f"fake {operation} failure")
        if self.config.mode is FakeMode.TIMEOUT:
            raise FakeTimeoutError(f"fake {operation} timeout")


def _bounded_unique(ids: Iterable[str], limit: int) -> tuple[str, ...]:
    result: list[str] = []
    for item_id in ids:
        if not item_id.strip():
            raise ValueError("identifiers must be non-empty")
        if item_id not in result:
            result.append(item_id)
        if len(result) > limit:
            raise ValueError("item limit exceeded")
    return tuple(result)


class FakeDiscoveryRepository(_FakeProvider):
    """Tenant-scoped catalog and profile repository."""

    def __init__(
        self,
        experiences: tuple[ExperienceRecord, ...] = (),
        profiles: tuple[UserProfile, ...] = (),
        config: FakeConfig | None = None,
    ) -> None:
        super().__init__(config)
        if len(experiences) > self.config.max_items or len(profiles) > self.config.max_items:
            raise ValueError("repository collections exceed the configured item limit")
        self._experiences = tuple(experiences)
        self._profiles = tuple(profiles)

    def read_catalog(
        self,
        context: ImmersiveDiscoveryContext,
        experience_ids: tuple[str, ...] = (),
    ) -> tuple[ExperienceRecord, ...]:
        ids = _bounded_unique(experience_ids, self.config.max_items)
        self._record("read_catalog", context, ids)
        allowed = set(ids)
        return tuple(
            experience
            for experience in self._experiences
            if experience.tenant_id == context.request_context.tenant_id
            and (not allowed or experience.experience_id in allowed)
        )

    def read_profile(self, context: ImmersiveDiscoveryContext) -> UserProfile | None:
        self._record("read_profile", context)
        return next(
            (
                profile
                for profile in self._profiles
                if profile.tenant_id == context.request_context.tenant_id
                and profile.user_id == context.request_context.principal_id
            ),
            None,
        )


class FakeCandidateSource(_FakeProvider):
    """Candidate source that applies hard eligibility before returning results."""

    def __init__(
        self,
        experiences: tuple[ExperienceRecord, ...],
        user: UserProfile,
        config: FakeConfig | None = None,
    ) -> None:
        super().__init__(config)
        if len(experiences) > self.config.max_items:
            raise ValueError("candidate collection exceeds the configured item limit")
        self._experiences = tuple(experiences)
        self._user = user

    def retrieve(self, context: ImmersiveDiscoveryContext, limit: int = 20) -> tuple[FakeCandidate, ...]:
        if not 1 <= limit <= self.config.max_items:
            raise ValueError("limit is outside the configured bounds")
        self._record("retrieve", context)
        candidates = [
            FakeCandidate(experience_id=experience.experience_id, source="fake", score=1 / (index + 1))
            for index, experience in enumerate(self._experiences)
            if evaluate_eligibility(experience, self._user, context).eligible
        ]
        return tuple(candidates[:limit])


class FakeFeatureProvider(_FakeProvider):
    """Deterministic feature hydration for eligible candidate identifiers."""

    def __init__(self, features: tuple[FakeFeature, ...] = (), config: FakeConfig | None = None) -> None:
        super().__init__(config)
        if len(features) > self.config.max_items:
            raise ValueError("feature collection exceeds the configured item limit")
        self._features = {feature.experience_id: feature for feature in features}

    def hydrate(
        self,
        context: ImmersiveDiscoveryContext,
        candidates: tuple[FakeCandidate, ...],
    ) -> tuple[FakeFeature, ...]:
        if len(candidates) > self.config.max_items:
            raise ValueError("candidate collection exceeds the configured item limit")
        ids = _bounded_unique((candidate.experience_id for candidate in candidates), self.config.max_items)
        self._record("hydrate", context, ids)
        return tuple(self._features[experience_id] for experience_id in ids if experience_id in self._features)


class FakeRanker(_FakeProvider):
    """Deterministic ranker with stable score and identifier tie-breaking."""

    def rank(
        self,
        context: ImmersiveDiscoveryContext,
        candidates: tuple[FakeCandidate, ...],
        features: tuple[FakeFeature, ...] = (),
    ) -> tuple[FakeRankedCandidate, ...]:
        if len(candidates) > self.config.max_items or len(features) > self.config.max_items:
            raise ValueError("ranking inputs exceed the configured item limit")
        ids = _bounded_unique((candidate.experience_id for candidate in candidates), self.config.max_items)
        self._record("rank", context, ids)
        feature_scores = {
            feature.experience_id: sum(value for _, value in feature.values) / max(len(feature.values), 1)
            for feature in features
        }
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                -(candidate.score + feature_scores.get(candidate.experience_id, 0.0)),
                candidate.experience_id,
            ),
        )
        return tuple(
            FakeRankedCandidate(
                experience_id=candidate.experience_id,
                score=min(1.0, candidate.score + feature_scores.get(candidate.experience_id, 0.0)),
                rank=rank,
            )
            for rank, candidate in enumerate(ordered, start=1)
        )
