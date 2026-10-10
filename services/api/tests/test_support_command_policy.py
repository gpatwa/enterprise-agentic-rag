import pytest
from pydantic import ValidationError

from app.support.command_policy import (
    PolicyOutcome,
    PolicyReasonCode,
    evaluate_support_command,
)
from app.support.commands import SupportCommand


def command(**overrides):
    value = {
        "command_type": "add_internal_note", "parameters": {"note": "Investigating"},
        "evidence_ids": ["ticket-1"], "idempotency_key": "req-1", "risk_level": "low",
        "approval_requirement": "not_required", "contract_version": "support-command.v1",
        "context": {"tenant_id": "tenant-a", "principal_id": "agent-1"},
    }
    value.update(overrides)
    return SupportCommand.model_validate(value)


def test_permits_only_low_risk_commands_without_approval():
    decision = evaluate_support_command(command())
    assert decision.outcome is PolicyOutcome.PERMIT_QUEUEING
    assert decision.reason_code is PolicyReasonCode.ALLOWED
    assert decision.tenant_id == "tenant-a"
    assert decision.evidence_ids == ("ticket-1",)


def test_approval_is_required_and_model_cannot_lower_baseline_risk():
    decision = evaluate_support_command(command(command_type="send_customer_reply", risk_level="low", approval_requirement="not_required"))
    assert decision.outcome is PolicyOutcome.REQUIRE_HUMAN_REVIEW
    assert decision.reason_code is PolicyReasonCode.RISK_ESCALATION


@pytest.mark.parametrize("overrides,reason", [
    ({"contract_version": "support-command.v2"}, PolicyReasonCode.INVALID_CONTRACT_VERSION),
    ({"evidence_ids": []}, PolicyReasonCode.MISSING_EVIDENCE),
    ({"context": {"tenant_id": " ", "principal_id": "agent-1"}}, PolicyReasonCode.INVALID_CONTEXT),
    ({"risk_level": "high", "approval_requirement": "required"}, PolicyReasonCode.HIGH_RISK),
])
def test_unsafe_commands_are_denied(overrides, reason):
    # Context/evidence invalidity is rejected by the command contract itself; policy
    # still handles malformed runtime objects defensively.
    if overrides.get("evidence_ids") == [] or overrides.get("context", {}).get("tenant_id") == " ":
        object.__setattr__(cmd := command(), "evidence_ids", tuple(overrides.get("evidence_ids", cmd.evidence_ids)))
        if "context" in overrides:
            object.__setattr__(cmd, "context", object.__new__(type(cmd.context)))
            object.__setattr__(cmd.context, "tenant_id", " ")
            object.__setattr__(cmd.context, "principal_id", "agent-1")
    else:
        cmd = command(**overrides)
    assert evaluate_support_command(cmd).reason_code is reason


def test_decision_is_frozen_and_has_no_action_capability():
    decision = evaluate_support_command(command())
    with pytest.raises(ValidationError):
        decision.outcome = PolicyOutcome.DENY
    assert not hasattr(decision, "execute")
    assert not hasattr(decision, "approve")
