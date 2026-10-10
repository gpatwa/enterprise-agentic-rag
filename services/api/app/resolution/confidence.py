"""Deterministic confidence calibration and abstention policy."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.resolution.models import ConfidenceLevel


class ConfidenceReason(str, Enum):
    """Bounded reasons explaining a policy decision."""

    VERIFIED_EVIDENCE = "verified_evidence"
    STRONG_VERIFIED_EVIDENCE = "strong_verified_evidence"
    VERIFIER_REJECTED = "verifier_rejected"
    NO_EVIDENCE = "no_evidence"
    NO_SUPPORTED_CLAIMS = "no_supported_claims"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ConfidencePolicyDecision(BaseModel):
    """Immutable result of the resolution confidence policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence: ConfidenceLevel
    abstain: bool
    reason_codes: tuple[ConfidenceReason, ...] = Field(min_length=1, max_length=4)
    next_action: str

    @field_validator("reason_codes")
    @classmethod
    def _unique_reasons(cls, value: tuple[ConfidenceReason, ...]) -> tuple[ConfidenceReason, ...]:
        if len(set(value)) != len(value):
            raise ValueError("reason_codes must be unique")
        return value


def _level(value: ConfidenceLevel | str) -> ConfidenceLevel:
    try:
        return value if isinstance(value, ConfidenceLevel) else ConfidenceLevel(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("model_confidence must be low, medium, or high") from exc


def _non_negative(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def decide_confidence(
    *,
    model_confidence: ConfidenceLevel | str,
    verifier_status: str,
    supported_claim_count: int,
    evidence_count: int,
    conflicting_evidence: bool = False,
) -> ConfidencePolicyDecision:
    """Apply policy gates; model confidence is only a ceiling, never a gate bypass."""
    model_level = _level(model_confidence)
    supported_claim_count = _non_negative("supported_claim_count", supported_claim_count)
    evidence_count = _non_negative("evidence_count", evidence_count)
    if not isinstance(verifier_status, str) or not verifier_status.strip():
        raise ValueError("verifier_status must be a non-blank string")
    if not isinstance(conflicting_evidence, bool):
        raise ValueError("conflicting_evidence must be a boolean")

    reasons: list[ConfidenceReason] = []
    if verifier_status != "verified":
        reasons.append(ConfidenceReason.VERIFIER_REJECTED)
    if evidence_count == 0:
        reasons.append(ConfidenceReason.NO_EVIDENCE)
    if supported_claim_count == 0:
        reasons.append(ConfidenceReason.NO_SUPPORTED_CLAIMS)
    if conflicting_evidence:
        reasons.append(ConfidenceReason.CONFLICTING_EVIDENCE)

    if reasons:
        return ConfidencePolicyDecision(
            confidence=ConfidenceLevel.LOW,
            abstain=True,
            reason_codes=tuple(reasons),
            next_action="route_to_human",
        )

    # One supported claim and one evidence item is the minimum safe outcome.
    if evidence_count < 1 or supported_claim_count < 1:
        return ConfidencePolicyDecision(
            confidence=ConfidenceLevel.LOW,
            abstain=True,
            reason_codes=(ConfidenceReason.INSUFFICIENT_EVIDENCE,),
            next_action="route_to_human",
        )

    calibrated = ConfidenceLevel.HIGH if evidence_count >= 2 and supported_claim_count >= 2 else ConfidenceLevel.MEDIUM
    # Self-confidence cannot promote a weakly supported result, but may lower it.
    if model_level == ConfidenceLevel.LOW:
        calibrated = ConfidenceLevel.LOW
    reason = ConfidenceReason.STRONG_VERIFIED_EVIDENCE if calibrated == ConfidenceLevel.HIGH else ConfidenceReason.VERIFIED_EVIDENCE
    return ConfidencePolicyDecision(
        confidence=calibrated,
        abstain=False,
        reason_codes=(reason,),
        next_action="suggest_agent_response",
    )


evaluate_confidence_policy = decide_confidence

__all__ = ["ConfidencePolicyDecision", "ConfidenceReason", "decide_confidence", "evaluate_confidence_policy"]
