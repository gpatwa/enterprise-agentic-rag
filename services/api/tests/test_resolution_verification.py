import pytest

from app.resolution.evidence import EvidenceItem, EvidencePacket
from app.resolution.models import GroundedResolutionOutcome
from app.resolution.verification import verify_resolution


def packet(*, source_id="s1", snippet="Restart the export worker before retrying."):
    item = EvidenceItem(label="[E1]", document_id="d1", source_id=source_id, source_type="kb", title="Export", snippet=snippet, query="export", retrieval_mode="lexical", index_version="i1", content_version="c1", permission_version="p1")
    return EvidencePacket(packet_version="v1", items=(item,))


def outcome(**changes):
    values = dict(claims=[{"text": "Restart the export worker before retrying", "citation_labels": ["[E1]"]}], citations=[{"label": "[E1]", "source_id": "s1"}], steps=[{"instruction": "Restart the export worker", "citation_labels": ["[E1]"]}], customer_response="Restart the export worker.", confidence="high", abstention=False, next_action="suggest_agent_response")
    values.update(changes)
    return GroundedResolutionOutcome(**values)


def test_verified_result_is_frozen_and_counts_supported_claims():
    result = verify_resolution(outcome(), packet())
    assert result.status == "verified"
    assert result.supported_claim_count == 1
    assert result.allowed_labels == ("[E1]",)
    with pytest.raises(Exception):
        result.status = "rejected"


@pytest.mark.parametrize("change", [
    {"citations": [{"label": "[E9]", "source_id": "s1"}], "claims": [{"text": "Restart the export worker", "citation_labels": ["[E9]"]}]},
    {"citations": [{"label": "[E1]", "source_id": "other"}]},
    {"claims": [{"text": "The account is permanently deleted", "citation_labels": ["[E1]"]}]},
])
def test_rejects_unknown_lineage_or_unsupported_claim(change):
    result = verify_resolution(outcome(**change), packet())
    assert result.status == "rejected"
    assert result.errors


def test_abstention_and_action_inconsistencies_are_rejected():
    result = verify_resolution(outcome(abstention=True, next_action="suggest_agent_response"), packet())
    assert "abstention requires route_to_human" in result.errors

