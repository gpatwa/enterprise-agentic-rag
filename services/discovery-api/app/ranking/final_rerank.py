"""Deterministic list-level safety and quality reranking.

This module is deliberately closed-world: it may remove or reorder supplied
candidates, but it never creates candidates or turns an ineligible candidate
into an eligible one.  Soft list constraints may relax only to fill the
requested bounded list.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_TOKEN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_MAX_CANDIDATES = 500
_MAX_REASONS = 8


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class Relaxation(str, Enum):
    NONE = "none"
    CREATOR_CAP = "creator_cap"
    REPETITION_CAP = "repetition_cap"
    FRESHNESS_FLOOR = "freshness_floor"
    DIVERSITY = "diversity"


class FinalRerankCandidate(_FrozenModel):
    """Candidate metadata needed for list constraints, with redacted evidence."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    original_rank: int = Field(ge=1, le=_MAX_CANDIDATES)
    creator_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    category: str = Field(min_length=1, max_length=128, pattern=_TOKEN)
    freshness: float = Field(ge=0, le=1, allow_inf_nan=False)
    eligible: bool = True
    safety_approved: bool = True
    blocked: bool = False
    source: str = Field(min_length=1, max_length=64, pattern=_TOKEN)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)

    @model_validator(mode="after")
    def validate_evidence(self) -> "FinalRerankCandidate":
        values = (*self.reason_codes, *self.evidence)
        if any(not value or len(value) > 64 for value in values):
            raise ValueError("reason codes and evidence must be bounded")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason codes must be unique")
        return self


class FinalRerankPolicy(_FrozenModel):
    """Versioned, bounded list policy; all constraints except safety are soft."""

    policy_version: str = Field(default="final-rerank-v1", min_length=1, max_length=128, pattern=_VERSION)
    model_version: str = Field(default="utility-v1", min_length=1, max_length=128, pattern=_VERSION)
    limit: int = Field(default=20, ge=1, le=_MAX_CANDIDATES)
    max_per_creator: int = Field(default=2, ge=1, le=_MAX_CANDIDATES)
    max_per_category: int = Field(default=3, ge=1, le=_MAX_CANDIDATES)
    min_freshness: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    min_categories: int = Field(default=1, ge=1, le=_MAX_CANDIDATES)


class FinalRerankItem(_FrozenModel):
    """Final item with bounded, non-sensitive explanations."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    source: str = Field(min_length=1, max_length=64, pattern=_TOKEN)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    original_rank: int = Field(ge=1, le=_MAX_CANDIDATES)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)
    relaxation: Relaxation = Relaxation.NONE
    eligible: Literal[True] = True


class FinalRerankResult(_FrozenModel):
    """Closed-world final list and the versions used to produce it."""

    policy_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    items: tuple[FinalRerankItem, ...] = Field(max_length=_MAX_CANDIDATES)
    filtered_ineligible: int = Field(ge=0, le=_MAX_CANDIDATES)
    relaxed: tuple[Relaxation, ...] = Field(default_factory=tuple, max_length=4)

    @model_validator(mode="after")
    def validate_result(self) -> "FinalRerankResult":
        ids = tuple(item.candidate_id for item in self.items)
        if len(ids) != len(set(ids)):
            raise ValueError("final list candidate IDs must be unique")
        if len(set(self.relaxed)) != len(self.relaxed):
            raise ValueError("relaxations must be unique")
        return self


class FinalReranker:
    """Apply hard safety first, then bounded list-level soft constraints.

    Relaxation order is fixed and intentionally conservative:
    creator cap, repetition/category cap, freshness floor, then diversity.
    A constraint is relaxed only when its strict form would prevent filling
    the requested list; hard eligibility, safety, and blocked rules never
    relax.
    """

    _RELAXATION_ORDER = (
        Relaxation.CREATOR_CAP,
        Relaxation.REPETITION_CAP,
        Relaxation.FRESHNESS_FLOOR,
        Relaxation.DIVERSITY,
    )

    def __init__(self, policy: FinalRerankPolicy | None = None) -> None:
        self.policy = policy or FinalRerankPolicy()

    def rerank(self, candidates: Sequence[FinalRerankCandidate]) -> FinalRerankResult:
        supplied = tuple(candidates)
        if len(supplied) > _MAX_CANDIDATES:
            raise ValueError("candidate batch exceeds bound")
        ids = tuple(candidate.candidate_id for candidate in supplied)
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")

        # The model contract makes normal construction eligible-only; this
        # explicit gate also protects callers passing compatible subclasses.
        eligible = tuple(
            candidate for candidate in supplied
            if candidate.eligible and candidate.safety_approved and not candidate.blocked
        )
        filtered = len(supplied) - len(eligible)
        selected: list[FinalRerankCandidate] = []
        relaxed: list[Relaxation] = []
        admitted_by: dict[str, Relaxation] = {}
        for candidate in self._ordered(eligible):
            if len(selected) >= self.policy.limit:
                break
            if self._allowed(candidate, selected, set(relaxed)):
                selected.append(candidate)

        for relaxation in self._RELAXATION_ORDER:
            if len(selected) >= self.policy.limit:
                break
            remaining = [item for item in eligible if item not in selected]
            if not remaining:
                break
            stage_relaxed = set(self._RELAXATION_ORDER[: self._RELAXATION_ORDER.index(relaxation) + 1])
            admitted = []
            selected_before_stage = tuple(selected)
            for candidate in self._ordered(remaining):
                if len(selected) >= self.policy.limit:
                    break
                if self._allowed(candidate, selected, stage_relaxed):
                    selected.append(candidate)
                    required_index = next(
                        index
                        for index in range(self._RELAXATION_ORDER.index(relaxation) + 1)
                        if self._allowed(
                            candidate,
                            selected_before_stage,
                            set(self._RELAXATION_ORDER[: index + 1]),
                        )
                    )
                    admitted.append((candidate, required_index))
                    admitted_by[candidate.candidate_id] = self._RELAXATION_ORDER[required_index]
            if admitted:
                for candidate, required_index in admitted:
                    for stage in self._RELAXATION_ORDER[: required_index + 1]:
                        if self._violates(candidate, selected_before_stage, stage) and stage not in relaxed:
                            relaxed.append(stage)

        items = tuple(
            FinalRerankItem(
                candidate_id=item.candidate_id,
                source=item.source,
                score=item.score,
                original_rank=item.original_rank,
                reason_codes=tuple(dict.fromkeys((*item.reason_codes, "final_rerank"))),
                evidence=tuple(dict.fromkeys((*item.evidence, "eligibility_hard_filter", "list_constraints"))),
                relaxation=admitted_by.get(item.candidate_id, Relaxation.NONE),
            )
            for item in selected
        )
        return FinalRerankResult(
            policy_version=self.policy.policy_version,
            model_version=self.policy.model_version,
            items=items,
            filtered_ineligible=filtered,
            relaxed=tuple(relaxed),
        )

    def _allowed(
        self, candidate: FinalRerankCandidate, selected: Sequence[FinalRerankCandidate], relaxed: set[Relaxation]
    ) -> bool:
        creators = Counter(item.creator_id for item in selected)
        categories = Counter(item.category for item in selected)
        if Relaxation.CREATOR_CAP not in relaxed and creators[candidate.creator_id] >= self.policy.max_per_creator:
            return False
        if Relaxation.REPETITION_CAP not in relaxed and categories[candidate.category] >= self.policy.max_per_category:
            return False
        if Relaxation.FRESHNESS_FLOOR not in relaxed and candidate.freshness < self.policy.min_freshness:
            return False
        if Relaxation.DIVERSITY not in relaxed:
            categories_seen = set(categories)
            if len(categories_seen | {candidate.category}) < min(self.policy.min_categories, len(selected) + 1):
                return False
        return True

    def _violates(
        self,
        candidate: FinalRerankCandidate,
        selected: Sequence[FinalRerankCandidate],
        relaxation: Relaxation,
    ) -> bool:
        creators = Counter(item.creator_id for item in selected)
        categories = Counter(item.category for item in selected)
        if relaxation is Relaxation.CREATOR_CAP:
            return creators[candidate.creator_id] >= self.policy.max_per_creator
        if relaxation is Relaxation.REPETITION_CAP:
            return categories[candidate.category] >= self.policy.max_per_category
        if relaxation is Relaxation.FRESHNESS_FLOOR:
            return candidate.freshness < self.policy.min_freshness
        categories_seen = set(categories)
        return len(categories_seen | {candidate.category}) < min(self.policy.min_categories, len(selected) + 1)

    @staticmethod
    def _ordered(candidates: Sequence[FinalRerankCandidate]) -> tuple[FinalRerankCandidate, ...]:
        return tuple(sorted(candidates, key=lambda item: (-item.score, item.original_rank, item.candidate_id)))

def final_rerank(
    candidates: Sequence[FinalRerankCandidate], *, policy: FinalRerankPolicy | None = None
) -> FinalRerankResult:
    """Convenience entry point for the closed-world final reranker."""
    return FinalReranker(policy).rerank(candidates)


__all__ = [
    "FinalRerankCandidate",
    "FinalRerankItem",
    "FinalRerankPolicy",
    "FinalRerankResult",
    "FinalReranker",
    "Relaxation",
    "final_rerank",
]
