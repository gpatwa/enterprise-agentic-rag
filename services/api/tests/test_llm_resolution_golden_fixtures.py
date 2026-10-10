from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "llm_resolution" / "cases.json"
SEARCH_FIXTURE = Path(__file__).parent / "fixtures" / "search" / "documents.json"
REQUIRED_EXPECTED = {
    "intent", "entities", "constraints", "exact_terms", "acceptable_query_concepts",
    "supported_claims", "forbidden_claims", "confidence_band", "abstain",
    "allowed_action_types", "minimum_approval", "minimum_risk",
}


def _load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_llm_resolution_cases_are_complete_and_reference_stable_search_ids():
    cases = _load(FIXTURE)
    documents = _load(SEARCH_FIXTURE)
    document_ids = {document["document_id"] for document in documents}
    case_ids = [case["case_id"] for case in cases]

    assert len(cases) >= 12
    assert len(case_ids) == len(set(case_ids))
    assert all(case["tags"] for case in cases)
    assert all(REQUIRED_EXPECTED <= set(case["expected"]) for case in cases)
    assert all(case["expected"]["confidence_band"] in {"low", "medium", "high"} for case in cases)
    assert all(isinstance(case["expected"]["abstain"], bool) for case in cases)
    assert all(
        evidence["document_id"] in document_ids
        for case in cases
        for evidence in case["authorized_evidence"]
    )


def test_llm_resolution_cases_preserve_adversarial_boundaries():
    cases = _load(FIXTURE)
    tags = {tag for case in cases for tag in case["tags"]}
    assert {"vague_ticket", "exact_error", "conflicting_evidence", "weak_evidence"} <= tags
    assert {"prompt_injection", "acl_conflict", "unsafe_action", "abstention"} <= tags
    assert any(case["expected"]["abstain"] for case in cases)
    assert any(not case["expected"]["abstain"] for case in cases)
    assert any("draft_" in action for case in cases for action in case["expected"]["allowed_action_types"])

    for case in cases:
        if "prompt_injection" in case["tags"]:
            assert case["ticket"]["metadata"].get("unsafe_fixture_text") or any(
                evidence.get("unsafe_fixture_text") for evidence in case["authorized_evidence"]
            )
        authorized = {evidence["document_id"] for evidence in case["authorized_evidence"]}
        assert authorized.isdisjoint(case.get("unauthorized_evidence_ids", []))

    cross_tenant = next(case for case in cases if "cross_tenant" in case["tags"])
    assert "acme-ticket-1001" not in {
        evidence["document_id"] for evidence in cross_tenant["authorized_evidence"]
    }
