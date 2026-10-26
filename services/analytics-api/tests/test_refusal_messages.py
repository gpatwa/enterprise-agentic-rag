"""A refusal tells the person what to do next without revealing counts, policy values, or which records were involved."""

from app.runtime.analyze_service import _refusal

BASE = {
    "query_id": "q1",
    "tenant_id": "tenant-a",
    "user_id": "u1",
    "dataset": "orders",
    "generated_at": "2026-10-25T00:00:00Z",
}


def test_small_groups_are_explained_and_a_broader_question_is_suggested():
    outcome = _refusal(BASE, ["run-123:cohort_too_small"])  # the result stage prefixes the run id
    assert outcome.reason_code == "policy_restricted"
    assert "too small" in outcome.explanation and "broader grouping" in outcome.remediation
    assert not any(ch.isdigit() for ch in outcome.explanation + outcome.remediation)  # no thresholds or counts


def test_an_unauthorized_purpose_is_reported_as_unauthorized():
    outcome = _refusal(BASE, ["bootstrap:purpose_not_authorized"])
    assert outcome.reason_code == "unauthorized" and "purpose" in outcome.explanation


def test_any_other_policy_refusal_stays_generic_but_actionable():
    outcome = _refusal(BASE, ["policy:deny-123", "policy-filter:ValueError"])
    assert outcome.reason_code == "policy_restricted"
    assert "policy-filter" not in outcome.explanation and "deny-123" not in outcome.remediation
    assert outcome.remediation
