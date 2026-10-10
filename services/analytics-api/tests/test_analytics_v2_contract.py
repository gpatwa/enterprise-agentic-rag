"""Round-trip and mismatch tests for the additive analytics v2 outcome model."""
from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from packages.platform_contracts.analytics import AnalyticsQueryResponse
from packages.platform_contracts.analytics_v2 import AnalyticsV2Outcome, AnalyticsV2Response

OUTCOME_ADAPTER = TypeAdapter(AnalyticsV2Outcome)
BASE = {"query_id": "q-1", "tenant_id": "tenant-a", "user_id": "user-a", "dataset": "olist"}


@pytest.mark.parametrize(
    "payload",
    [
        {**BASE, "outcome": "answer", "answer": "BRL 370.00", "evidence": {"metric_ids": ["revenue"]}},
        {**BASE, "outcome": "clarify", "questions": [{"id": "period", "prompt": "Which period?"}]},
        {**BASE, "outcome": "refuse", "reason_code": "unauthorized", "explanation": "Access is denied."},
        {
            **BASE,
            "outcome": "review",
            "review_id": "review-1",
            "risk_reasons": ["uncertified metric"],
            "expires_at": datetime(2026, 8, 21, tzinfo=timezone.utc),
            "allowed_actions": ["approve", "reject"],
        },
        {**BASE, "outcome": "failed", "error_code": "query_timeout", "message": "Timed out.", "retryable": True},
    ],
)
def test_v2_outcomes_round_trip(payload):
    response = AnalyticsV2Response.model_validate(payload)

    assert response.root.outcome == payload["outcome"]
    assert AnalyticsV2Response.model_validate_json(response.model_dump_json()) == response


def test_v2_discriminator_rejects_mismatched_payload():
    with pytest.raises(ValidationError):
        OUTCOME_ADAPTER.validate_python({**BASE, "outcome": "answer", "questions": []})


def test_v2_evidence_defaults_are_not_shared():
    first = AnalyticsV2Response.model_validate({**BASE, "outcome": "answer", "answer": "One"})
    second = AnalyticsV2Response.model_validate({**BASE, "outcome": "answer", "answer": "Two"})

    first.root.evidence.metric_ids.append("revenue")
    assert second.root.evidence.metric_ids == []


def test_v2_answer_evidence_carries_provenance_policy_and_review_reference():
    response = AnalyticsV2Response.model_validate(
        {
            **BASE,
            "outcome": "answer",
            "answer": "BRL 370.00",
            "assumptions": ["Delivered orders only"],
            "confidence": 0.92,
            "review": {"review_id": "review-1", "state": "approved"},
            "evidence": {
                "provenance": [
                    {
                        "asset_id": "metric.revenue",
                        "asset_type": "metric",
                        "version": "2026-08-20",
                    }
                ],
                "policy_decision": {
                    "decision_id": "policy-1",
                    "effect": "allow",
                    "policy_version": "v1",
                    "enforced_filter_ids": ["tenant_scope"],
                },
            },
        }
    )

    assert response.root.evidence.provenance[0].asset_id == "metric.revenue"
    assert response.root.evidence.policy_decision.effect == "allow"
    assert response.root.review.state == "approved"


def test_v2_schema_has_an_outcome_discriminator():
    schema = AnalyticsV2Response.model_json_schema()

    assert schema["discriminator"]["propertyName"] == "outcome"


def test_v1_contract_remains_unchanged():
    response = AnalyticsQueryResponse(
        query_id="q-v1", query="Revenue", dataset="olist", status="succeeded"
    )

    assert response.contract_version == "v1"
