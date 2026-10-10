"""Deterministic trust gate for typed support command proposals."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.support.commands import (
    ApprovalRequirement,
    RiskLevel,
    SupportCommand,
    SupportCommandType,
)


class SupportCommandPolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PolicyOutcome(str, Enum):
    DENY = "deny"
    REQUIRE_HUMAN_REVIEW = "require_human_review"
    PERMIT_QUEUEING = "permit_queueing"


class PolicyReasonCode(str, Enum):
    INVALID_COMMAND = "invalid_command"
    UNKNOWN_COMMAND_TYPE = "unknown_command_type"
    INVALID_CONTRACT_VERSION = "invalid_contract_version"
    INVALID_CONTEXT = "invalid_context"
    MISSING_EVIDENCE = "missing_evidence"
    HIGH_RISK = "high_risk"
    RISK_ESCALATION = "risk_escalation"
    APPROVAL_REQUIRED = "approval_required"
    ALLOWED = "allowed"


class SupportCommandPolicyDecision(SupportCommandPolicyModel):
    outcome: PolicyOutcome
    reason_code: PolicyReasonCode
    contract_version: str = Field(min_length=1, max_length=32)
    tenant_id: str = Field(max_length=255)
    principal_id: str = Field(max_length=255)
    evidence_ids: tuple[str, ...] = Field(max_length=32)


_CONTRACT_VERSION = "support-command.v1"
_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
_BASELINE_RISK = {
    SupportCommandType.ADD_INTERNAL_NOTE: RiskLevel.LOW,
    SupportCommandType.ASSIGN_TICKET: RiskLevel.MEDIUM,
    SupportCommandType.SEND_CUSTOMER_REPLY: RiskLevel.MEDIUM,
    SupportCommandType.UPDATE_TICKET_STATUS: RiskLevel.MEDIUM,
}


def evaluate_support_command(command: SupportCommand) -> SupportCommandPolicyDecision:
    """Classify a proposal; this result cannot execute or approve anything."""
    version = getattr(command, "contract_version", "")
    context = getattr(command, "context", None)
    evidence_ids = getattr(command, "evidence_ids", ())
    tenant_id = getattr(context, "tenant_id", "") if context else ""
    principal_id = getattr(context, "principal_id", "") if context else ""

    def decision(outcome: PolicyOutcome, reason: PolicyReasonCode) -> SupportCommandPolicyDecision:
        return SupportCommandPolicyDecision(
            outcome=outcome, reason_code=reason, contract_version=version or "unknown",
            tenant_id=tenant_id, principal_id=principal_id, evidence_ids=tuple(evidence_ids),
        )

    if version != _CONTRACT_VERSION:
        return decision(PolicyOutcome.DENY, PolicyReasonCode.INVALID_CONTRACT_VERSION)
    if not tenant_id.strip() or not principal_id.strip():
        return decision(PolicyOutcome.DENY, PolicyReasonCode.INVALID_CONTEXT)
    if not evidence_ids or any(not isinstance(item, str) or not item.strip() for item in evidence_ids):
        return decision(PolicyOutcome.DENY, PolicyReasonCode.MISSING_EVIDENCE)

    command_type = getattr(command, "command_type", None)
    baseline = _BASELINE_RISK.get(command_type)
    if baseline is None:
        return decision(PolicyOutcome.DENY, PolicyReasonCode.UNKNOWN_COMMAND_TYPE)
    if _RISK_ORDER[command.risk_level] < _RISK_ORDER[baseline]:
        return decision(PolicyOutcome.REQUIRE_HUMAN_REVIEW, PolicyReasonCode.RISK_ESCALATION)
    if command.risk_level is RiskLevel.HIGH:
        return decision(PolicyOutcome.DENY, PolicyReasonCode.HIGH_RISK)
    if command.approval_requirement is ApprovalRequirement.REQUIRED:
        return decision(PolicyOutcome.REQUIRE_HUMAN_REVIEW, PolicyReasonCode.APPROVAL_REQUIRED)
    return decision(PolicyOutcome.PERMIT_QUEUEING, PolicyReasonCode.ALLOWED)


assess_support_command = evaluate_support_command

__all__ = [
    "PolicyOutcome", "PolicyReasonCode", "SupportCommandPolicyDecision",
    "evaluate_support_command", "assess_support_command",
]
