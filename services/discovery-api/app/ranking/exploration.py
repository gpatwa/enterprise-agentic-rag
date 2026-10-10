"""Bounded, deterministic exploration for immersive discovery."""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import AgeRating, Availability, ConsentState, SafetyState

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_MAX_CANDIDATES = 500
_MAX_REASONS = 8
_AGE_ORDER = {AgeRating.E: 0, AgeRating.E10: 1, AgeRating.T: 2}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class ExplorationCandidate(_FrozenModel):
    """Candidate metadata required before an item may be explored."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    creator_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    quality_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    age_rating: AgeRating
    safety_state: SafetyState
    availability: Availability
    personalization_required: bool = False
    blocked: bool = False
    eligible: bool = True
    prior_exposures: int = Field(default=0, ge=0, le=_MAX_CANDIDATES)


class ExplorationPolicy(_FrozenModel):
    """Versioned, bounded exploration controls."""

    policy_version: str = Field(default="exploration-v1", min_length=1, max_length=128, pattern=_VERSION)
    seed: str = Field(default="default", min_length=1, max_length=128, pattern=_ID)
    enabled: bool = True
    per_request_budget: int = Field(default=3, ge=0, le=_MAX_CANDIDATES)
    per_user_budget: int = Field(default=20, ge=0, le=_MAX_CANDIDATES)
    max_candidate_exposures: int = Field(default=1, ge=0, le=_MAX_CANDIDATES)
    max_per_creator: int = Field(default=1, ge=1, le=_MAX_CANDIDATES)
    minimum_quality: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)


class ExplorationRequest(_FrozenModel):
    """Request-scoped policy inputs; all identity and consent values are explicit."""

    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    user_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    age_rating_limit: AgeRating
    consent_state: ConsentState
    user_exposures: int = Field(default=0, ge=0, le=_MAX_CANDIDATES)
    blocked_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_CANDIDATES)
    candidates: tuple[ExplorationCandidate, ...] = Field(min_length=1, max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_inputs(self) -> "ExplorationRequest":
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        if len(self.blocked_ids) != len(set(self.blocked_ids)):
            raise ValueError("blocked IDs must be unique")
        return self


class ExplorationEvidence(_FrozenModel):
    """Redacted reason evidence for the exploration decision."""

    candidate_id: str | None = Field(default=None, max_length=255, pattern=_ID)
    selected: bool
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=_MAX_REASONS)


class ExplorationResult(_FrozenModel):
    """Bounded selected candidates and deterministic decision evidence."""

    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    policy_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    candidates: tuple[ExplorationCandidate, ...] = Field(max_length=_MAX_CANDIDATES)
    evidence: tuple[ExplorationEvidence, ...] = Field(max_length=_MAX_CANDIDATES)
    fallback: bool
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)

    @model_validator(mode="after")
    def validate_result(self) -> "ExplorationResult":
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("selected candidate IDs must be unique")
        if len(self.candidates) > len(self.evidence):
            raise ValueError("selected candidates require evidence")
        return self


class ExplorationPolicyRunner:
    """Filter hard policy first, then choose a stable bounded sample."""

    def __init__(self, policy: ExplorationPolicy | None = None) -> None:
        self.policy = policy or ExplorationPolicy()

    def select(self, request: ExplorationRequest) -> ExplorationResult:
        if not self.policy.enabled:
            return self._fallback(request, "kill_switch")

        budget = min(
            self.policy.per_request_budget,
            max(0, self.policy.per_user_budget - request.user_exposures),
        )
        if budget == 0:
            return self._fallback(request, "budget_exhausted")

        eligible: list[tuple[str, ExplorationCandidate]] = []
        rejected: list[ExplorationEvidence] = []
        blocked = set(request.blocked_ids)
        for candidate in request.candidates:
            reasons = self._rejection_reasons(candidate, request, blocked)
            if reasons:
                rejected.append(ExplorationEvidence(candidate_id=candidate.candidate_id, selected=False, reason_codes=tuple(reasons)))
                continue
            digest = hashlib.sha256(
                f"{self.policy.seed}:{request.tenant_id}:{request.user_id}:{request.request_id}:{candidate.candidate_id}".encode(
                    "utf-8"
                )
            ).hexdigest()
            eligible.append((digest, candidate))

        ordered = sorted(eligible, key=lambda item: (item[0], item[1].candidate_id))
        selected: list[ExplorationCandidate] = []
        creator_counts: dict[str, int] = {}
        for _, candidate in ordered:
            if len(selected) >= budget:
                break
            if creator_counts.get(candidate.creator_id, 0) >= self.policy.max_per_creator:
                continue
            creator_counts[candidate.creator_id] = creator_counts.get(candidate.creator_id, 0) + 1
            selected.append(candidate)

        evidence = tuple(rejected)
        evidence += tuple(
            ExplorationEvidence(candidate_id=candidate.candidate_id, selected=True, reason_codes=("eligible", "seeded_selection"))
            for candidate in selected
        )
        if not selected:
            return self._fallback(request, "no_eligible_candidates", evidence=evidence)
        reasons = ("bounded_budget", "hard_policy_filter", "creator_cap", "seeded_selection")
        return ExplorationResult(
            request_id=request.request_id,
            policy_version=self.policy.policy_version,
            candidates=tuple(selected),
            evidence=evidence,
            fallback=False,
            reason_codes=reasons,
        )

    def _rejection_reasons(
        self, candidate: ExplorationCandidate, request: ExplorationRequest, blocked: set[str]
    ) -> list[str]:
        reasons: list[str] = []
        if candidate.tenant_id != request.tenant_id:
            reasons.append("tenant_scope")
        if candidate.candidate_id in blocked or candidate.blocked:
            reasons.append("blocked")
        if not candidate.eligible:
            reasons.append("ineligible")
        if candidate.safety_state is not SafetyState.APPROVED:
            reasons.append("safety")
        if candidate.availability is not Availability.AVAILABLE:
            reasons.append("availability")
        if _AGE_ORDER[candidate.age_rating] > _AGE_ORDER[request.age_rating_limit]:
            reasons.append("age_rating")
        if candidate.quality_score < self.policy.minimum_quality:
            reasons.append("quality")
        if candidate.personalization_required and request.consent_state is not ConsentState.PERSONALIZATION_ALLOWED:
            reasons.append("consent")
        if candidate.prior_exposures >= self.policy.max_candidate_exposures:
            reasons.append("candidate_exposure_cap")
        return reasons

    def _fallback(
        self,
        request: ExplorationRequest,
        reason: str,
        *,
        evidence: tuple[ExplorationEvidence, ...] = (),
    ) -> ExplorationResult:
        return ExplorationResult(
            request_id=request.request_id,
            policy_version=self.policy.policy_version,
            candidates=(),
            evidence=evidence
            + (ExplorationEvidence(candidate_id=None, selected=False, reason_codes=(reason,)),),
            fallback=True,
            reason_codes=(reason,),
        )


def select_exploration(
    request: ExplorationRequest, *, policy: ExplorationPolicy | None = None
) -> ExplorationResult:
    """Convenience entry point for bounded exploration selection."""

    return ExplorationPolicyRunner(policy).select(request)


__all__ = [
    "ExplorationCandidate",
    "ExplorationEvidence",
    "ExplorationPolicy",
    "ExplorationPolicyRunner",
    "ExplorationRequest",
    "ExplorationResult",
    "select_exploration",
]
