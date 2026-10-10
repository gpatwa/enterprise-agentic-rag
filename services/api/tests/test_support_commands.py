import pytest
from pydantic import ValidationError

from app.support.commands import (
    ApprovalRequirement,
    RiskLevel,
    SupportCommand,
    SupportCommandType,
)


def command(**overrides):
    data = {
        "command_type": "add_internal_note",
        "parameters": {"note": "Investigating the issue"},
        "evidence_ids": ["ticket-1", "article-2"],
        "idempotency_key": "req-123",
        "risk_level": "low",
        "approval_requirement": "not_required",
        "contract_version": "support-command.v1",
        "context": {"tenant_id": "tenant-a", "principal_id": "agent-1"},
    }
    data.update(overrides)
    return SupportCommand.model_validate(data)


def test_valid_command_is_frozen_and_typed():
    value = command()
    assert value.command_type is SupportCommandType.ADD_INTERNAL_NOTE
    assert value.risk_level is RiskLevel.LOW
    with pytest.raises(ValidationError):
        value.parameters = {}


@pytest.mark.parametrize("field,value", [
    ("command_type", " "),
    ("command_type", "delete_everything"),
])
def test_command_type_is_allowlisted_and_nonblank(field, value):
    with pytest.raises(ValidationError):
        command(**{field: value})


def test_rejects_extra_fields_duplicate_evidence_and_unbounded_parameters():
    with pytest.raises(ValidationError):
        command(unexpected=True)
    with pytest.raises(ValidationError):
        command(evidence_ids=["same", "same"])
    with pytest.raises(ValidationError):
        command(parameters={"note": "x" * 1001})
    with pytest.raises(ValidationError):
        command(parameters={"nested": {"unsafe": True}})


@pytest.mark.parametrize("risk,approval", [("medium", "not_required"), ("high", "not_required")])
def test_rejects_invalid_risk_approval_combinations(risk, approval):
    with pytest.raises(ValidationError):
        command(risk_level=risk, approval_requirement=approval)


def test_low_risk_command_may_still_require_approval():
    value = command(approval_requirement="required")
    assert value.risk_level is RiskLevel.LOW
    assert value.approval_requirement is ApprovalRequirement.REQUIRED
