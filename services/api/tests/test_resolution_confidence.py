import pytest

from app.resolution.confidence import ConfidenceReason, decide_confidence
from app.resolution.models import ConfidenceLevel


def test_verified_evidence_produces_deterministic_non_abstention():
    decision = decide_confidence(
        model_confidence="high", verifier_status="verified", supported_claim_count=2, evidence_count=2
    )
    assert decision.confidence == ConfidenceLevel.HIGH
    assert decision.abstain is False
    assert decision.reason_codes == (ConfidenceReason.STRONG_VERIFIED_EVIDENCE,)
    assert decision.next_action == "suggest_agent_response"


@pytest.mark.parametrize("kwargs", [
    {"verifier_status": "rejected", "supported_claim_count": 2, "evidence_count": 2},
    {"verifier_status": "verified", "supported_claim_count": 1, "evidence_count": 0},
    {"verifier_status": "verified", "supported_claim_count": 0, "evidence_count": 1},
    {"verifier_status": "verified", "supported_claim_count": 1, "evidence_count": 1, "conflicting_evidence": True},
])
def test_hard_policy_gates_always_abstain(kwargs):
    decision = decide_confidence(model_confidence="high", **kwargs)
    assert decision.abstain is True
    assert decision.confidence == ConfidenceLevel.LOW
    assert decision.next_action == "route_to_human"


def test_model_confidence_cannot_promote_or_bypass_policy():
    decision = decide_confidence(model_confidence="low", verifier_status="verified", supported_claim_count=1, evidence_count=1)
    assert decision.confidence == ConfidenceLevel.LOW
    assert decision.abstain is False


def test_decision_is_frozen_and_inputs_are_bounded():
    decision = decide_confidence(model_confidence="medium", verifier_status="verified", supported_claim_count=1, evidence_count=1)
    with pytest.raises(Exception):
        decision.abstain = True
    with pytest.raises(ValueError):
        decide_confidence(model_confidence="high", verifier_status="verified", supported_claim_count=-1, evidence_count=1)
