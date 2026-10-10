import pytest

from app.resolution.commands import generate_support_command
from app.resolution.evidence import EvidenceItem, EvidencePacket
from app.resolution.models import GroundedResolutionOutcome
from app.resolution.verification import verify_resolution
from app.support.commands import SupportTenantPrincipalContext


def packet(*, source_id="s1", snippet="Restart the export worker before retrying."):
    return EvidencePacket(packet_version="v1", items=(EvidenceItem(
        label="[E1]", document_id="d1", source_id=source_id, source_type="kb",
        title="Export", snippet=snippet, metadata=(), query="export",
        retrieval_mode="lexical", index_version="i1", content_version="c1",
        permission_version="p1",
    ),))


def outcome(**changes):
    values = dict(
        claims=[{"text": "Restart the export worker before retrying", "citation_labels": ["[E1]"]}],
        citations=[{"label": "[E1]", "source_id": "s1"}],
        steps=[{"instruction": "Restart the export worker", "citation_labels": ["[E1]"]}],
        customer_response="Restart the export worker before retrying.", confidence="high",
        abstention=False, next_action="draft_agent_response",
    )
    values.update(changes)
    return GroundedResolutionOutcome(**values)


CONTEXT = SupportTenantPrincipalContext(tenant_id="tenant-a", principal_id="agent-1")


def proposal(value=None, evidence=None):
    evidence = evidence or packet()
    value = value or outcome()
    verification = verify_resolution(value, evidence)
    return generate_support_command(value, verification, evidence, CONTEXT)


def test_generates_typed_draft_response_with_lineage_and_stable_key():
    command = proposal()
    assert command is not None
    assert command.command_type.value == "send_customer_reply"
    assert command.parameters == {"response": "Restart the export worker before retrying."}
    assert command.evidence_ids == ("s1",)
    assert command.approval_requirement.value == "required"
    assert command.idempotency_key == proposal().idempotency_key


@pytest.mark.parametrize("value", [outcome(abstention=True, next_action="route_to_human"), outcome(next_action="unknown_action")])
def test_no_command_for_abstention_or_unsupported_action(value):
    assert proposal(value) is None


def test_no_command_for_rejected_verification():
    value = outcome(claims=[{"text": "Unsupported claim", "citation_labels": ["[E1]"]}])
    assert proposal(value) is None


def test_no_command_when_citations_are_missing():
    value = outcome()
    empty = EvidencePacket(packet_version="v1", items=())
    assert proposal(value, empty) is None
