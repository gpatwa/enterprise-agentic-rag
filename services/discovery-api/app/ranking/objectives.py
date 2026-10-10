"""Bounded multi-objective utility policy for eligible discovery candidates."""
from __future__ import annotations

import re
from enum import Enum
from math import isfinite
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_NAME = r"^[a-z][a-z0-9_]{0,63}$"
_MAX_OBJECTIVES = 16
_MAX_CANDIDATES = 500
_MAX_EVIDENCE = 8


class ObjectiveName(str, Enum):
    QUALIFIED_PLAY = "qualified_play"
    SATISFACTION = "satisfaction"
    RETURN = "return"
    SAVE = "save"
    NEGATIVE_FEEDBACK = "negative_feedback"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class ObjectiveSpec(_FrozenModel):
    """One reviewed objective and its bounded contribution to utility."""

    name: ObjectiveName
    weight: float = Field(ge=0, le=1, allow_inf_nan=False)
    cap: float = Field(default=1, gt=0, le=1, allow_inf_nan=False)
    penalty: bool = False

    @model_validator(mode="after")
    def validate_penalty(self) -> "ObjectiveSpec":
        if self.name is ObjectiveName.NEGATIVE_FEEDBACK and not self.penalty:
            raise ValueError("negative_feedback must be a penalty objective")
        if self.name is not ObjectiveName.NEGATIVE_FEEDBACK and self.penalty:
            raise ValueError("only negative_feedback may be a penalty objective")
        return self


class UtilityPolicy(_FrozenModel):
    """Versioned, kill-switchable policy; it never performs eligibility."""

    policy_version: str = Field(default="utility-v1", min_length=1, max_length=128, pattern=_VERSION)
    objectives: tuple[ObjectiveSpec, ...] = Field(default_factory=lambda: (
        ObjectiveSpec(name=ObjectiveName.QUALIFIED_PLAY, weight=0.30, cap=1),
        ObjectiveSpec(name=ObjectiveName.SATISFACTION, weight=0.25, cap=1),
        ObjectiveSpec(name=ObjectiveName.RETURN, weight=0.20, cap=1),
        ObjectiveSpec(name=ObjectiveName.SAVE, weight=0.15, cap=1),
        ObjectiveSpec(name=ObjectiveName.NEGATIVE_FEEDBACK, weight=0.10, cap=1, penalty=True),
    ), min_length=1, max_length=_MAX_OBJECTIVES)
    safety_penalty: float = Field(default=0.25, ge=0, le=1, allow_inf_nan=False)
    enabled: bool = True
    kill_switch: bool = False

    @model_validator(mode="after")
    def validate_policy(self) -> "UtilityPolicy":
        names = tuple(item.name for item in self.objectives)
        if len(set(names)) != len(names):
            raise ValueError("objective names must be unique")
        if sum(item.weight for item in self.objectives) <= 0:
            raise ValueError("at least one objective must have positive weight")
        if not any(item.name is ObjectiveName.NEGATIVE_FEEDBACK for item in self.objectives):
            raise ValueError("negative_feedback must be explicitly configured")
        return self

    @property
    def active(self) -> bool:
        return self.enabled and not self.kill_switch


class UtilitySignals(_FrozenModel):
    """Candidate predictions/signals normalized to the closed interval [0, 1]."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    base_score: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    signals: Mapping[str, float] = Field(default_factory=dict, max_length=_MAX_OBJECTIVES)
    safety_risk: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    eligible: bool = True
    original_rank: int = Field(default=1, ge=1, le=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_signals(self) -> "UtilitySignals":
        for name, value in self.signals.items():
            if not isinstance(name, str) or not re.fullmatch(_NAME, name):
                raise ValueError("signal names must be bounded lowercase names")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
                raise ValueError("signals must be finite numeric values")
            if not 0 <= value <= 1:
                raise ValueError("signals must be between 0 and 1")
        return self


class UtilityScore(_FrozenModel):
    """Auditable score; evidence contains names and bounded values only."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    policy_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    components: Mapping[str, float] = Field(default_factory=dict, max_length=_MAX_OBJECTIVES)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_EVIDENCE)
    fallback: bool
    eligible: bool = True
    original_rank: int = Field(ge=1, le=_MAX_CANDIDATES)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


class MultiObjectiveUtility:
    """Apply a reviewed policy without granting eligibility or adding candidates."""

    def __init__(self, policy: UtilityPolicy | None = None) -> None:
        self.policy = policy or UtilityPolicy()

    def score(self, candidate: UtilitySignals) -> UtilityScore | None:
        if not candidate.eligible:
            return None
        if not self.policy.active:
            return UtilityScore(
                candidate_id=candidate.candidate_id,
                policy_version=self.policy.policy_version,
                score=candidate.base_score,
                components={},
                evidence=("utility_fallback",),
                fallback=True,
                original_rank=candidate.original_rank,
            )
        components: dict[str, float] = {}
        total = 0.0
        for objective in self.policy.objectives:
            raw = candidate.signals.get(objective.name.value, 0.0)
            contribution = min(objective.cap, max(0.0, raw)) * objective.weight
            if objective.penalty:
                contribution = -contribution
            components[objective.name.value] = round(contribution, 12)
            total += contribution
        safety = min(1.0, candidate.safety_risk * self.policy.safety_penalty)
        components["safety_penalty"] = round(-safety, 12)
        total = _clamp(candidate.base_score + total - safety)
        return UtilityScore(
            candidate_id=candidate.candidate_id,
            policy_version=self.policy.policy_version,
            score=total,
            components=components,
            evidence=tuple(["utility_policy", *(["safety_penalty"] if safety else [])])[:_MAX_EVIDENCE],
            fallback=False,
            original_rank=candidate.original_rank,
        )

    def rank(self, candidates: Sequence[UtilitySignals]) -> tuple[UtilityScore, ...]:
        if not candidates:
            return ()
        if len(candidates) > _MAX_CANDIDATES:
            raise ValueError("candidate batch exceeds bound")
        ids = tuple(item.candidate_id for item in candidates)
        if len(set(ids)) != len(ids):
            raise ValueError("candidate IDs must be unique")
        scores = tuple(result for candidate in candidates if (result := self.score(candidate)) is not None)
        return tuple(sorted(scores, key=lambda item: (-item.score, item.original_rank, item.candidate_id)))


def apply_utility_policy(
    candidates: Sequence[UtilitySignals], *, policy: UtilityPolicy | None = None
) -> tuple[UtilityScore, ...]:
    """Convenience entry point for deterministic closed-world utility ranking."""
    return MultiObjectiveUtility(policy).rank(candidates)


__all__ = [
    "MultiObjectiveUtility",
    "ObjectiveName",
    "ObjectiveSpec",
    "UtilityPolicy",
    "UtilityScore",
    "UtilitySignals",
    "apply_utility_policy",
]
