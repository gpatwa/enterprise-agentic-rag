"""Immutable, content-addressed evidence envelope for one terminal analytics run (ADS-042).

The envelope holds fingerprints, identifiers, and stable codes only: no SQL, parameters,
policy values, result rows, or free-text reasons. Each terminal kind has required
provenance, enforced by the model itself so an incomplete envelope cannot be built.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.platform_contracts.agent_runtime import TerminalKind

EVIDENCE_ENVELOPE_VERSION = "v1"
_HEX64 = r"^[0-9a-f]{64}$"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyEvidence(_Frozen):
    decision_id: str = Field(min_length=1, max_length=255)
    effect: Literal["allow", "deny", "review"]
    reasons: tuple[str, ...] = Field(min_length=1)
    policy_version: str = Field(min_length=1, max_length=255)
    enforced_filter_ids: tuple[str, ...] = ()


class CostEvidence(_Frozen):
    estimated_cost_units: float | None = Field(default=None, ge=0)
    requires_approval: bool | None = None
    reason: str | None = Field(default=None, max_length=255)
    observed_cost_units: float | None = Field(default=None, ge=0)


class ApprovalEvidence(_Frozen):
    state: str = Field(min_length=1, max_length=64)
    review_kind: str | None = Field(default=None, max_length=64)
    review_id: str | None = Field(default=None, max_length=255)
    plan_fingerprint: str | None = Field(default=None, max_length=128)


class ResultEvidence(_Frozen):
    result_fingerprint: str = Field(pattern=_HEX64)
    plan_fingerprint: str = Field(pattern=_HEX64)
    validation_status: Literal["valid", "valid_with_warnings", "invalid"]
    validation_fingerprint: str = Field(pattern=_HEX64)
    row_count: int = Field(ge=0)
    issue_codes: tuple[str, ...] = ()


class ClarificationEvidence(_Frozen):
    ambiguity_codes: tuple[str, ...] = Field(min_length=1)
    continuation_count: int = Field(ge=0)


class CancellationEvidence(_Frozen):
    requested_by: str = Field(min_length=1, max_length=255)
    policy_source: str = Field(min_length=1, max_length=255)
    reason_fingerprint: str = Field(pattern=_HEX64)
    requested_at: datetime


class ErrorEvidence(_Frozen):
    code: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1, max_length=255)


class TransitionEvidence(_Frozen):
    sequence: int = Field(ge=1)
    from_node: str = Field(min_length=1, max_length=255)
    to_node: str | None = Field(default=None, max_length=255)
    to_status: str = Field(min_length=1, max_length=64)
    evidence_fingerprints: tuple[str, ...] = ()


class EvidenceEnvelopeBody(_Frozen):
    """Everything an envelope asserts, validated for required provenance."""

    envelope_version: Literal["v1"] = EVIDENCE_ENVELOPE_VERSION
    tenant_id: str = Field(min_length=1, max_length=255)
    run_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    graph_version: str = Field(min_length=1, max_length=255)
    terminal_kind: TerminalKind
    context_snapshot_id: str = Field(min_length=1, max_length=255)
    intent_fingerprint: str | None = Field(default=None, pattern=_HEX64)
    semantic_contract: str | None = Field(default=None, max_length=512)
    policy: PolicyEvidence | None = None
    cost: CostEvidence | None = None
    approval: ApprovalEvidence | None = None
    result: ResultEvidence | None = None
    clarification: ClarificationEvidence | None = None
    cancellation: CancellationEvidence | None = None
    errors: tuple[ErrorEvidence, ...] = ()
    transitions: tuple[TransitionEvidence, ...] = Field(min_length=1)
    terminal_summary_reference: str = Field(min_length=1, max_length=255)
    terminal_evidence_fingerprints: tuple[str, ...] = Field(min_length=1)
    completed_at: datetime

    @model_validator(mode="after")
    def enforce_required_provenance(self) -> "EvidenceEnvelopeBody":
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("envelope completed_at must be timezone-aware")
        sequences = [item.sequence for item in self.transitions]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("envelope transitions must be contiguous from 1")
        if self.transitions[-1].to_status != "terminal" or self.transitions[-1].to_node is not None:
            raise ValueError("envelope must end with the terminal transition")
        problems = _kind_problems(self, {error.code for error in self.errors})
        if problems:
            raise ValueError(f"{self.terminal_kind} evidence is incomplete: {', '.join(problems)}")
        return self

    def compute_fingerprint(self) -> str:
        return fingerprint_payload(self.model_dump(mode="json", exclude={"content_fingerprint"}))


class EvidenceEnvelope(EvidenceEnvelopeBody):
    content_fingerprint: str = Field(pattern=_HEX64)

    @property
    def envelope_id(self) -> str:
        return f"evidence:{self.content_fingerprint[:32]}"

    @model_validator(mode="after")
    def enforce_content_address(self) -> "EvidenceEnvelope":
        if self.compute_fingerprint() != self.content_fingerprint:
            raise ValueError("envelope content_fingerprint does not match content")
        return self

    @classmethod
    def build(cls, **values: Any) -> "EvidenceEnvelope":
        body = EvidenceEnvelopeBody(**values)
        return cls(**body.model_dump(), content_fingerprint=body.compute_fingerprint())


def fingerprint_payload(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _kind_problems(envelope: EvidenceEnvelopeBody, codes: set[str]) -> list[str]:
    missing: list[str] = []

    def need(condition: bool, label: str) -> None:
        if not condition:
            missing.append(label)

    kind = envelope.terminal_kind
    if kind == "succeeded":
        need(envelope.intent_fingerprint is not None, "intent_fingerprint")
        need(envelope.semantic_contract is not None, "semantic_contract")
        need(envelope.policy is not None and envelope.policy.effect == "allow", "allowing policy decision")
        need(envelope.cost is not None and envelope.cost.estimated_cost_units is not None, "cost estimate")
        need(
            envelope.result is not None and envelope.result.validation_status != "invalid",
            "acceptable result validation",
        )
        if envelope.approval is not None:
            need(envelope.approval.state == "approved", "approved review")
    elif kind == "refused":
        need("policy_denied" in codes, "policy_denied error")
    elif kind == "review_required":
        need("stale_context" in codes, "stale_context error")
    elif kind == "clarification_required":
        need(envelope.clarification is not None, "clarification")
    elif kind == "failed":
        need(bool(envelope.errors), "error")
    elif kind == "cancelled":
        need(envelope.cancellation is not None, "cancellation")
    return missing
