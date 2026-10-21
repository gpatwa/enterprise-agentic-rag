"""M7 fix D13: policy values go when the run ends; plans and links go after the retention period; paused runs keep theirs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from reference_stack.stack import build_stack
from sqlalchemy import text

from app.resilience.retention import purge_run_material


def _counts(engine):
    with engine.connect() as connection:
        return {
            t: connection.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            for t in ("analytics_run_policy_values", "analytics_run_plans", "analytics_run_result_links")
        }


def test_policy_values_go_at_once_and_plans_after_the_retention_period(tmp_path):
    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    stack.service().analyze(
        who, purpose="analytics", idempotency_key="ret-key-0000001", request_text="Show monthly revenue"
    )
    engine = stack.control.engine
    assert _counts(engine) == {
        "analytics_run_policy_values": 1,
        "analytics_run_plans": 1,
        "analytics_run_result_links": 1,
    }
    assert purge_run_material(engine) == {"policy_values": 1, "result_links": 0, "plans": 0}
    later = datetime.now(timezone.utc) + timedelta(days=31)
    assert purge_run_material(engine, now=later) == {"policy_values": 0, "result_links": 1, "plans": 1}
    assert set(_counts(engine).values()) == {0}


def test_a_paused_run_keeps_its_material_until_it_ends(tmp_path):
    stack = build_stack("duckdb", tmp_path, review_threshold=1e-9)
    who = stack.verifier().verify(stack.token("requester"))
    paused = stack.service().analyze(
        who, purpose="analytics", idempotency_key="ret-key-0000002", request_text="Show monthly revenue"
    )
    assert paused.state == "waiting_review"
    later = datetime.now(timezone.utc) + timedelta(days=90)
    assert purge_run_material(stack.control.engine, now=later) == {"policy_values": 0, "result_links": 0, "plans": 0}
    review = stack.control.get_review(paused.outcome.review_id, tenant_id="tenant-a", purpose="analytics")
    reviewer = stack.verifier().verify(stack.token("reviewer"))
    done = stack.service().decide_review(
        reviewer,
        purpose="analytics",
        run_id=paused.run_id,
        decision="approved",
        plan_fingerprint=review.plan_fingerprint,
        note=None,
    )
    assert done.state == "terminal"  # the approved plan was still there to run


def test_runs_transitions_and_evidence_are_never_touched(tmp_path):
    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    stack.service().analyze(
        who, purpose="analytics", idempotency_key="ret-key-0000003", request_text="Show monthly revenue"
    )
    engine = stack.control.engine
    tables = ("analytics_agent_runs", "analytics_run_transitions", "analytics_evidence_envelopes")
    with engine.connect() as connection:
        before = {t: connection.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in tables}
    purge_run_material(engine, now=datetime.now(timezone.utc) + timedelta(days=365))
    with engine.connect() as connection:
        assert {t: connection.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in tables} == before
    with pytest.raises(ValueError):
        purge_run_material(engine, plan_retention_days=0)
