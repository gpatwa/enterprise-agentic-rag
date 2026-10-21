"""The read-only review brief: facts for a reviewer or the review assistant, decisions for the reviewer only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from reference_stack.stack import build_stack

URL = "/api/v2/analytics"


def _paused(tmp_path, **kwargs):
    stack = build_stack("duckdb", tmp_path, review_threshold=1e-9, **kwargs)
    client = TestClient(stack.app())
    headers = {"Authorization": f"Bearer {stack.token('requester')}", "Idempotency-Key": "brief-key-0000001"}
    paused = client.post(
        f"{URL}/analyze", json={"request_text": "Show monthly revenue", "purpose": "analytics"}, headers=headers
    ).json()
    assert paused["state"] == "waiting_review"
    return stack, client, paused


def _get(client, stack, run_id, user):
    return client.get(
        f"{URL}/runs/{run_id}/review-brief",
        params={"purpose": "analytics"},
        headers={"Authorization": f"Bearer {stack.token(user)}"},
    )


def test_a_reviewer_gets_the_facts_and_nothing_changes(tmp_path):
    stack, client, paused = _paused(tmp_path)
    before = stack.control.replay_transitions(run_id=paused["run_id"], tenant_id="tenant-a", purpose="analytics")
    reply = _get(client, stack, paused["run_id"], "reviewer")
    assert reply.status_code == 200, reply.text
    brief = reply.json()
    assert (
        brief["review_id"] == paused["outcome"]["review_id"]
        and brief["plan_fingerprint"] == paused["outcome"]["plan_fingerprint"]
    )
    assert brief["metrics"] == ["revenue"] and brief["dialect"] == "duckdb" and "sales_orders" in brief["sql"]
    assert brief["advisory"]["decision_authority"] == "none" and {c["name"] for c in brief["checks"]} >= {
        "plan_available",
        "within_run_cost_limit",
        "time_range_bounded",
    }
    assert "result" not in brief and "rows" not in brief  # a paused run has not executed
    assert stack.executed_sql == []
    assert (
        stack.control.replay_transitions(run_id=paused["run_id"], tenant_id="tenant-a", purpose="analytics") == before
    )


def test_the_review_assistant_can_read_the_brief_but_cannot_decide(tmp_path):
    stack, client, paused = _paused(tmp_path)
    assert _get(client, stack, paused["run_id"], "assistant-bot").status_code == 200
    body = {"purpose": "analytics", "decision": "approved", "plan_fingerprint": paused["outcome"]["plan_fingerprint"]}
    decided = client.post(
        f"{URL}/runs/{paused['run_id']}/review",
        json=body,
        headers={"Authorization": f"Bearer {stack.token('assistant-bot')}"},
    )
    assert decided.status_code == 403 and decided.json()["detail"] == "reviewer_role_required"
    assert stack.executed_sql == []


@pytest.mark.parametrize("user", ["requester", "colleague"])
def test_the_requester_and_other_colleagues_cannot_read_the_brief(tmp_path, user):
    stack, client, paused = _paused(tmp_path)
    reply = _get(client, stack, paused["run_id"], user)
    assert reply.status_code == 403 and reply.json()["detail"] == "reviewer_or_assistant_role_required"


def test_another_tenants_reviewer_gets_nothing(tmp_path):
    stack, client, paused = _paused(tmp_path)
    foreign = client.get(
        f"{URL}/runs/{paused['run_id']}/review-brief",
        params={"purpose": "analytics"},
        headers={"Authorization": f"Bearer {stack.token('reviewer', tenant='tenant-b')}"},
    )
    assert foreign.status_code == 404


def test_a_run_that_is_not_waiting_has_no_brief(tmp_path):
    stack = build_stack("duckdb", tmp_path)
    client = TestClient(stack.app())
    headers = {"Authorization": f"Bearer {stack.token('requester')}", "Idempotency-Key": "brief-key-0000002"}
    done = client.post(
        f"{URL}/analyze", json={"request_text": "Show monthly revenue", "purpose": "analytics"}, headers=headers
    ).json()
    reply = _get(client, stack, done["run_id"], "reviewer")
    assert reply.status_code == 409 and reply.json()["detail"] == "run_not_awaiting_review"


def test_a_missing_plan_is_flagged_as_do_not_approve(tmp_path):
    stack, client, paused = _paused(tmp_path)
    stack.plans._plans.clear()
    with stack.control.engine.begin() as connection:
        from sqlalchemy import text

        connection.execute(text("DELETE FROM analytics_run_plans"))
    brief = _get(client, stack, paused["run_id"], "reviewer").json()
    assert brief["sql"] is None and brief["advisory"]["suggestion"] == "needs_attention"
    assert any("plan_available" in reason for reason in brief["advisory"]["reasons"])


def test_the_brief_cannot_be_read_without_a_service_configured():
    from fastapi import FastAPI

    from app.api_v2 import V2Runtime, build_v2_router

    async def no_key():
        return None

    app = FastAPI()
    app.include_router(build_v2_router(V2Runtime(), no_key))
    assert TestClient(app).get(f"{URL}/runs/x/review-brief", params={"purpose": "analytics"}).status_code in {503, 401}


def test_pending_reviews_are_listed_for_reviewers_and_the_assistant_only(tmp_path):
    stack, client, paused = _paused(tmp_path)
    for user, status in (("reviewer", 200), ("assistant-bot", 200), ("requester", 403), ("colleague", 403)):
        reply = client.get(
            f"{URL}/reviews/pending",
            params={"purpose": "analytics"},
            headers={"Authorization": f"Bearer {stack.token(user)}"},
        )
        assert reply.status_code == status, user
    listed = client.get(
        f"{URL}/reviews/pending",
        params={"purpose": "analytics"},
        headers={"Authorization": f"Bearer {stack.token('reviewer')}"},
    ).json()
    assert [r["run_id"] for r in listed["reviews"]] == [paused["run_id"]]
    other = client.get(
        f"{URL}/reviews/pending",
        params={"purpose": "analytics"},
        headers={"Authorization": f"Bearer {stack.token('reviewer', tenant='tenant-b')}"},
    ).json()
    assert other["reviews"] == []  # another tenant's reviewer sees none of ours


def test_a_decided_review_leaves_the_pending_list(tmp_path):
    stack, client, paused = _paused(tmp_path)
    body = {"purpose": "analytics", "decision": "rejected", "plan_fingerprint": paused["outcome"]["plan_fingerprint"]}
    assert (
        client.post(
            f"{URL}/runs/{paused['run_id']}/review",
            json=body,
            headers={"Authorization": f"Bearer {stack.token('reviewer')}"},
        ).status_code
        == 200
    )
    listed = client.get(
        f"{URL}/reviews/pending",
        params={"purpose": "analytics"},
        headers={"Authorization": f"Bearer {stack.token('reviewer')}"},
    ).json()
    assert listed["reviews"] == []


def test_the_review_assistant_writes_a_note_and_changes_nothing(tmp_path):
    from app.decision_support.agent import run_once

    stack, client, paused = _paused(tmp_path)
    before = stack.control.replay_transitions(run_id=paused["run_id"], tenant_id="tenant-a", purpose="analytics")
    headers = {"Authorization": f"Bearer {stack.token('assistant-bot')}"}

    def get(path, params):
        reply = client.get(f"{URL}{path}", params=params, headers=headers)
        if reply.status_code in (404, 409):
            raise LookupError(path)
        reply.raise_for_status()
        return reply.json()

    notes = run_once(get)
    assert (
        len(notes) == 1
        and notes[0]["decision_authority"] == "none"
        and notes[0]["plan_fingerprint"] == paused["outcome"]["plan_fingerprint"]
    )
    assert "revenue" in notes[0]["summary"] and notes[0]["suggestion"] in {"looks_routine", "needs_attention"}
    assert stack.executed_sql == []
    assert (
        stack.control.replay_transitions(run_id=paused["run_id"], tenant_id="tenant-a", purpose="analytics") == before
    )
    review = stack.control.get_review(paused["outcome"]["review_id"], tenant_id="tenant-a", purpose="analytics")
    assert review.state == "pending"  # the assistant left the decision to a person
