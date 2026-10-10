"""ADS-050: feedback links the exact run, evidence, identity, and reason, and changes nothing else."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reference_stack import golden
from reference_stack.golden import run_golden
from reference_stack.stack import build_stack
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api_v2 import V2Runtime, build_v2_router
from app.runtime.evidence_store import EvidenceStore
from app.runtime.feedback_service import FeedbackService
from app.runtime.feedback_store import FeedbackStore
from packages.platform_contracts.feedback import FeedbackSubmission
from packages.platform_contracts.security import AnalyticsIdentity

URL = "/api/v2/analytics"
SERVICE = Path(__file__).resolve().parent.parent


def _headers(stack, user="analyst-2", key=None, **kwargs):
    headers = {"Authorization": f"Bearer {stack.token(user, **kwargs)}"}
    return {**headers, "Idempotency-Key": key} if key else headers


def _answer(stack, client, question="Show monthly revenue", key="key-answer-01"):
    response = client.post(
        f"{URL}/analyze",
        json={"request_text": question, "purpose": "analytics"},
        headers=_headers(stack, "requester", key),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _feedback(client, stack, run_id, body=None, key="fb-key-0001", **kwargs):
    body = body or {"purpose": "analytics", "verdict": "incorrect", "reason_code": "wrong_metric"}
    return client.post(f"{URL}/runs/{run_id}/feedback", json=body, headers=_headers(stack, key=key, **kwargs))


@pytest.fixture
def stack(tmp_path):
    return build_stack("duckdb", tmp_path)


@pytest.fixture
def client(stack):
    return TestClient(stack.app())


def test_feedback_links_the_exact_run_evidence_identity_and_reason(stack, client):
    run = _answer(stack, client)
    response = _feedback(
        client,
        stack,
        run["run_id"],
        {
            "purpose": "analytics",
            "verdict": "partially_correct",
            "reason_code": "wrong_time_range",
            "correction": {"target": "time_dimension", "semantic_id": "created_at"},
            "note": "I expected the last quarter.",
        },
    )
    assert response.status_code == 201, response.text
    receipt = response.json()
    envelope = stack.evidence.get(run["run_id"], tenant_id="tenant-a", purpose="analytics")
    record = stack.feedback_service().store.get(receipt["feedback_id"], tenant_id="tenant-a")
    assert receipt["evidence_fingerprint"] == record.evidence_fingerprint == envelope.content_fingerprint
    assert record.run_id == run["run_id"] and record.submitted_by == "analyst-2" and record.tenant_id == "tenant-a"
    assert record.reason_code == "wrong_time_range" and record.verdict == "partially_correct"
    assert record.result_fingerprint == run["outcome"]["evidence"]["result_fingerprint"]
    assert record.terminal_kind == "succeeded" and record.semantic_contract == "sales-core@v1"
    assert record.context_snapshot_id == envelope.context_snapshot_id and record.intent_fingerprint
    assert record.correction.semantic_id == "created_at" and record.note == "I expected the last quarter."


def test_the_service_path_seals_evidence_once(stack, client):
    run = _answer(stack, client)
    sealed = stack.evidence.get(run["run_id"], tenant_id="tenant-a", purpose="analytics")
    assert sealed.terminal_kind == "succeeded" and sealed.result is not None and sealed.policy is not None
    client.get(f"{URL}/runs/{run['run_id']}", params={"purpose": "analytics"}, headers=_headers(stack))
    _answer(stack, client)  # idempotent replay of the same run
    assert stack.evidence.verify_chain("tenant-a") == 1


def test_replays_are_idempotent_and_key_reuse_with_a_different_body_conflicts(stack, client):
    run = _answer(stack, client)
    first = _feedback(client, stack, run["run_id"])
    second = _feedback(client, stack, run["run_id"])
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["feedback_id"] == second.json()["feedback_id"] and second.json()["created"] is False
    other = _feedback(
        client, stack, run["run_id"], {"purpose": "analytics", "verdict": "unsafe", "reason_code": "policy_concern"}
    )
    assert other.status_code == 409 and other.json()["detail"] == "idempotency_key_reused"
    again = _feedback(client, stack, run["run_id"], key="fb-key-0002")
    assert again.json()["feedback_id"] != first.json()["feedback_id"]
    assert len(stack.feedback_service().store.for_run(run["run_id"], tenant_id="tenant-a")) == 2


def test_authentication_scope_and_strict_bodies(stack, client):
    run = _answer(stack, client)
    url = f"{URL}/runs/{run['run_id']}/feedback"
    body = {"purpose": "analytics", "verdict": "incorrect", "reason_code": "wrong_metric"}
    assert client.post(url, json=body, headers={"Idempotency-Key": "fb-key-0001"}).status_code == 401
    wrong_purpose = client.post(
        url, json={**body, "purpose": "billing"}, headers=_headers(stack, key="fb-key-0001", purposes=("billing",))
    )
    assert wrong_purpose.status_code == 404  # the run is not visible under another purpose
    unauthorized = client.post(url, json={**body, "purpose": "billing"}, headers=_headers(stack, key="fb-key-0001"))
    assert unauthorized.status_code == 403 and unauthorized.json()["detail"] == "purpose_not_authorized"
    foreign = client.post(url, json=body, headers=_headers(stack, key="fb-key-0001", tenant="tenant-b"))
    assert foreign.status_code in {403, 404}
    assert client.post(url, json=body, headers=_headers(stack)).status_code == 400  # missing key
    assert _feedback(client, stack, run["run_id"], {**body, "sql": "DROP TABLE x"}).status_code == 422
    assert _feedback(client, stack, run["run_id"], {**body, "note": "x" * 2_001}).status_code == 422
    assert _feedback(client, stack, "no-such-run").json()["detail"] == "run_not_found"
    assert stack.feedback_service().store.for_run(run["run_id"], tenant_id="tenant-a") == ()


def test_corrections_can_only_name_certified_semantic_ids_never_sql(stack, client):
    run = _answer(stack, client)

    def correction(target, semantic_id, key):
        body = {
            "purpose": "analytics",
            "verdict": "incorrect",
            "reason_code": "wrong_metric",
            "correction": {"target": target, "semantic_id": semantic_id},
        }
        return _feedback(client, stack, run["run_id"], body, key=key)

    assert correction("metric", "revenue", "fb-key-ok-01").status_code == 201
    assert correction("metric", "profit", "fb-key-bad-01").json()["detail"] == "unknown_semantic_id"
    assert (
        correction("metric", "status", "fb-key-bad-02").json()["detail"] == "unknown_semantic_id"
    )  # a dimension, not a metric
    assert correction("filter_field", "orders.status", "fb-key-ok-02").status_code == 201
    for payload in ("revenue; DROP TABLE orders", "SUM(amount)", "revenue--", "a b"):
        assert correction("metric", payload, "fb-key-bad-03").status_code == 422
    correct_with_fix = _feedback(
        client,
        stack,
        run["run_id"],
        {
            "purpose": "analytics",
            "verdict": "correct",
            "reason_code": "other",
            "correction": {"target": "metric", "semantic_id": "revenue"},
        },
        key="fb-key-bad-04",
    )
    assert correct_with_fix.status_code == 422


def test_feedback_needs_a_terminal_run_with_sealed_evidence(tmp_path):
    paused_stack = build_stack("duckdb", tmp_path / "a", review_threshold=1e-9)
    paused_client = TestClient(paused_stack.app())
    paused = _answer(paused_stack, paused_client)
    assert paused["state"] == "waiting_review"
    blocked = _feedback(paused_client, paused_stack, paused["run_id"])
    assert blocked.status_code == 409 and blocked.json()["detail"] == "run_not_terminal"

    stack = build_stack("duckdb", tmp_path / "b")
    run = _answer(stack, TestClient(stack.app()))
    unsealed = FeedbackService(
        stack.control,
        EvidenceStore(build_stack("duckdb", tmp_path / "c").control.engine),
        FeedbackStore(stack.control.engine),
        stack.contracts,
    )
    identity = AnalyticsIdentity(tenant_id="tenant-a", user_id="u", purposes=["analytics"])
    from app.runtime.analyze_service import ServiceError

    with pytest.raises(ServiceError) as raised:
        unsealed.submit(
            identity,
            run_id=run["run_id"],
            idempotency_key="fb-key-0001",
            submission=FeedbackSubmission(purpose="analytics", verdict="incorrect", reason_code="other"),
        )
    assert raised.value.code == "evidence_unavailable"


def test_refused_runs_can_receive_feedback_without_result_evidence(tmp_path):
    denied = build_stack("duckdb", tmp_path, denied=True)
    client = TestClient(denied.app())
    run = _answer(denied, client)
    assert run["outcome"]["outcome"] == "refuse"
    response = _feedback(
        client, denied, run["run_id"], {"purpose": "analytics", "verdict": "incorrect", "reason_code": "other"}
    )
    assert response.status_code == 201
    record = denied.feedback_service().store.get(response.json()["feedback_id"], tenant_id="tenant-a")
    assert record.terminal_kind == "refused" and record.result_fingerprint is None


def test_stored_feedback_holds_no_sql_rows_or_policy_values(stack, client):
    run = _answer(stack, client)
    receipt = _feedback(client, stack, run["run_id"]).json()
    raw = stack.feedback_service().store.get(receipt["feedback_id"], tenant_id="tenant-a").model_dump_json()
    for forbidden in ("sales_orders", "SELECT", "1969", "1468", "policy_values"):
        assert forbidden not in raw
    with stack.control.engine.connect() as connection:
        stored = connection.execute(text("SELECT payload FROM analytics_feedback")).scalar()
    assert "sales_orders" not in str(stored) and "SELECT" not in str(stored)


def test_the_feedback_table_is_append_only(stack, client):
    run = _answer(stack, client)
    _feedback(client, stack, run["run_id"])
    with stack.control.engine.begin() as connection:
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text("UPDATE analytics_feedback SET verdict='correct'"))
    with stack.control.engine.begin() as connection:
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text("DELETE FROM analytics_feedback"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_feedback_has_no_effect_on_goldens_thresholds_policy_or_contracts(stack, client):
    watched = [golden.CORPUS, golden.THRESHOLDS, *sorted((SERVICE / "semantic_registry/contracts").glob("*.json"))]
    before = [_digest(path) for path in watched]
    contract_before = stack.contracts.document.model_dump_json()
    run = _answer(stack, client)
    for n, (verdict, reason) in enumerate(
        (("unsafe", "policy_concern"), ("incorrect", "wrong_filter"), ("incorrect", "other"))
    ):
        assert (
            _feedback(
                client,
                stack,
                run["run_id"],
                {"purpose": "analytics", "verdict": verdict, "reason_code": reason},
                key=f"fb-key-009{n}",
            ).status_code
            == 201
        )
    assert [_digest(path) for path in watched] == before
    assert stack.contracts.document.model_dump_json() == contract_before
    # The same question still produces the same answer, and the golden suite still meets its thresholds.
    again = _answer(stack, client, key="key-answer-02")
    assert again["outcome"]["result"] == run["outcome"]["result"]
    assert run_golden()["meets_thresholds"]


def test_the_endpoint_is_inert_until_feedback_is_configured(stack):
    runtime = V2Runtime(service=stack.service(), verifier=stack.verifier(), feedback=None)
    app = FastAPI()

    async def no_key():
        return None

    app.include_router(build_v2_router(runtime, no_key))
    client = TestClient(app)
    run = _answer(stack, client)
    response = _feedback(client, stack, run["run_id"])
    assert response.status_code == 503 and response.json()["detail"] == "feedback_not_configured"
    assert (
        json.loads(FeedbackSubmission(purpose="p", verdict="unsafe", reason_code="other").model_dump_json())["verdict"]
        == "unsafe"
    )
