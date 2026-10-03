"""ADS-045: `/api/v2/analytics` auth, idempotency, status, and outcome contract tests.

Real graph-v2 stages, real DuckDB execution, real SQLite control store, and a real signed
JWT; only the intent model, search, and snapshot providers are local fakes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from test_ads039_graph_adversarial import (
    NOW,
    PURPOSE,
    SERVICE_ROOT,
    SNAPSHOT_ID,
    TENANT,
    ContractsProvider,
    IntentClient,
    OntologyProvider,
    SearchProvider,
    SnapshotProvider,
    _context,
    _database,
    _intent,
    _registry_document,
)

from app.api_v2 import V2Runtime, build_v2_router
from app.compiler import DuckDBCompilerAdapter
from app.compiler.service import CertifiedIntentCompiler
from app.execution import (
    DraftClaim,
    DuckDBGateway,
    ExecutionLimits,
    ExecutionResultStore,
    GatewayCostEstimator,
    GatewayExecutor,
    run_control_totals,
)
from app.runtime import (
    AgentGraphRunner,
    BootstrapRequest,
    ExplanationStore,
    certified_intent_node,
    clarification_node,
    compile_node,
    context_retrieval_node,
    estimate_node,
    explain_node,
    fake_execution_node,
    governed_graph_v2,
    identity_bootstrap_node,
    ontology_resolution_node,
    policy_node,
    result_validation_node,
    review_decision_node,
    structured_intent_node,
)
from app.runtime.analyze_service import AnswerMaterial, GovernedAnalyzeService
from app.runtime.governed_stages import CompiledPlanStore, PolicyValueStore, analytics_plan_node
from app.security import OIDCVerifier
from packages.platform_contracts.agent_runtime import AgentRunState, NodeOutput, RunBudget

SECRET = "local-test-only-secret"
ISSUER, AUDIENCE = "https://issuer.example", "analytics"


def _token(user="requester", purposes=(PURPOSE,), tenant=TENANT, **claims):
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": user,
        "tid": tenant,
        "groups": ["analyst"],
        "purposes": list(purposes),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        **claims,
    }
    return jwt.encode(payload, SECRET, algorithm="HS256", headers={"kid": "k1"})


def _auth(**kwargs):
    return {"Authorization": f"Bearer {_token(**kwargs)}"}


class Rig:
    """One shared set of stores, with a runner built per (identity, request) like production."""

    def __init__(self, control, tmp_path, *, ambiguous=False, threshold=1e9):
        connection = duckdb.connect()
        connection.execute("""CREATE TABLE sales_orders AS SELECT 'o' || i AS id, CAST(i AS DECIMAL(12,2)) AS amount,
            CASE WHEN i % 5 = 0 THEN 'refunded' ELSE 'paid' END AS status,
            TIMESTAMP '2024-01-01' + INTERVAL (i * 20) HOUR AS created_at FROM range(1, 101) t(i)""")
        connection.execute(f"COPY sales_orders TO '{tmp_path / 'sales_orders.parquet'}' (FORMAT PARQUET)")
        connection.close()
        self.control, self.threshold = control, threshold
        self.gateway = DuckDBGateway({"sales_orders": tmp_path / "sales_orders.parquet"}, allowed_root=tmp_path)
        self.document = _registry_document()
        self.context, self.ontology = _context(self.document, ambiguous=ambiguous)
        self.ambiguous = ambiguous
        self.plans, self.results, self.policy_values = CompiledPlanStore(), ExecutionResultStore(), PolicyValueStore()
        self.explanations = ExplanationStore()
        self.compiler = CertifiedIntentCompiler(SERVICE_ROOT / "semantic_registry", adapter=DuckDBCompilerAdapter())
        self.contracts = ContractsProvider(self.document)
        self.starts = 0

    def runner(self, identity, request: BootstrapRequest) -> AgentGraphRunner:
        self.starts += 1
        return AgentGraphRunner(self.control, governed_graph_v2(self.nodes(identity, request)), now=lambda: NOW)

    def nodes(self, identity, request: BootstrapRequest, review_store=None) -> dict:
        review_store = review_store or self.control
        gateways = {"duckdb": self.gateway}
        intent = _intent("api", ambiguous=self.ambiguous)
        intent["query_id"] = request.request_id

        def controls(node_input, i, c):
            return run_control_totals(
                i, c, compile_plan=lambda x, y: self.compiler.compile(x), gateway=self.gateway, limits=ExecutionLimits()
            )

        def explainer(sheet, violations):
            return [DraftClaim(f"First value is {sheet.get('cell:r0c1').value}.", ("cell:r0c1", "metric:revenue"))]

        def go(ni, nxt):
            return NodeOutput(run_id=ni.run_id, node_id=ni.node_id, status="completed", next_node=nxt)

        handlers = {
            "create": lambda ni: go(ni, "bootstrap"),
            "bootstrap": identity_bootstrap_node(request),
            "retrieve": context_retrieval_node(SnapshotProvider(self.context), SearchProvider()),
            "extract_intent": structured_intent_node(IntentClient(intent)),
            "resolve": ontology_resolution_node(self.contracts, OntologyProvider(self.ontology)),
            "clarify": clarification_node(),
            "plan": analytics_plan_node(self.contracts),
            "validate": certified_intent_node(self.contracts),
            "policy": policy_node(self.contracts, identity, self.policy_values, review_store=review_store),
            "compile": compile_node(self.compiler, self.plans, self.policy_values),
            "estimate": estimate_node(
                self.plans,
                GatewayCostEstimator(gateways),
                approval_threshold=self.threshold,
                review_store=review_store,
                requested_by=identity.user_id,
            ),
            "approve": review_decision_node(self.control),
            "execute": fake_execution_node(GatewayExecutor(self.plans, gateways, self.results, ExecutionLimits())),
            "result_validate": result_validation_node(self.plans, self.results, self.contracts, controls),
            "explain": explain_node(self.results, self.contracts, self.plans, explainer, self.explanations),
        }
        return handlers

    def new_state(self, request, run_id, purpose):
        return AgentRunState(
            run_id=run_id,
            request_id=request.request_id,
            tenant_id=request.identity.tenant_id,
            purpose=purpose,
            request_text=request.request_text.strip(),
            graph_version="graph-v2",
            current_node="create",
            context_snapshot_id=SNAPSHOT_ID,
            budget=RunBudget(deadline=NOW + timedelta(minutes=5), max_transitions=40, max_context_tokens=2_000),
        )

    def answer_for(self, state):
        return AnswerMaterial(
            self.results.get(state.tenant_id, state.run_id, state.execution_reference),
            self.explanations.get(state.tenant_id, state.run_id),
        )


def _client(tmp_path, monkeypatch, **rig_kwargs):
    control = _database(tmp_path, monkeypatch)
    rig = Rig(control, tmp_path, **rig_kwargs)
    runtime = V2Runtime(
        service=GovernedAnalyzeService(
            control, runner_factory=rig.runner, state_factory=rig.new_state, answers=rig, now=lambda: NOW
        ),
        verifier=OIDCVerifier(ISSUER, AUDIENCE, {"k1": SECRET}, algorithms=("HS256",)),
    )
    app = FastAPI()

    async def no_key():
        return None

    app.include_router(build_v2_router(runtime, no_key))
    return TestClient(app), rig, runtime, control


BODY = {"request_text": "Show monthly revenue", "purpose": PURPOSE}


def _post(client, key="key-0000001", body=BODY, **auth):
    return client.post("/api/v2/analytics/analyze", json=body, headers={**_auth(**auth), "Idempotency-Key": key})


def test_analyze_returns_a_grounded_answer_bound_to_the_validated_result(tmp_path, monkeypatch):
    client, rig, _, _ = _client(tmp_path, monkeypatch)
    response = _post(client)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["state"] == "terminal" and data["outcome"]["outcome"] == "answer"
    answer = data["outcome"]
    assert answer["explanation_status"] == "grounded" and answer["claims"][0]["cites"][0] == "cell:r0c1"
    assert answer["result"]["row_count"] == len(answer["result"]["rows"]) > 0
    assert answer["visualization"]["kind"] in {"line", "bar", "table", "stat"}
    assert answer["evidence"]["result_fingerprint"] and answer["evidence"]["metric_ids"]
    assert "sales_orders" not in response.text and "SELECT" not in response.text  # no SQL or physical names


def test_idempotent_replay_returns_the_same_run_without_re_executing(tmp_path, monkeypatch):
    client, rig, _, _ = _client(tmp_path, monkeypatch)
    first = _post(client).json()
    executed = rig.starts
    second = _post(client).json()
    assert second["run_id"] == first["run_id"] and second["outcome"]["result"] == first["outcome"]["result"]
    assert rig.starts == executed  # terminal run: nothing resumed
    other = _post(client, body={**BODY, "request_text": "A different question"})
    assert other.status_code == 409 and other.json()["detail"] == "idempotency_key_reused"
    assert _post(client, key="key-0000002").json()["run_id"] != first["run_id"]
    assert _post(client, key="key-0000001", user="someone-else").json()["run_id"] != first["run_id"]


def test_authentication_and_authorization_fail_closed(tmp_path, monkeypatch):
    client, _, runtime, _ = _client(tmp_path, monkeypatch)
    url = "/api/v2/analytics/analyze"
    assert client.post(url, json=BODY, headers={"Idempotency-Key": "key-0000001"}).status_code == 401
    assert (
        client.post(
            url, json=BODY, headers={"Authorization": "Bearer junk", "Idempotency-Key": "key-0000001"}
        ).status_code
        == 401
    )
    wrong_purpose = _post(client, purposes=("billing",))
    assert wrong_purpose.status_code == 403 and wrong_purpose.json()["detail"] == "purpose_not_authorized"
    assert _post(client, key="short").status_code == 400
    assert client.post(url, json=BODY, headers=_auth()).status_code == 400  # missing idempotency key
    assert (
        client.post(
            url, json={**BODY, "sql": "DROP"}, headers={**_auth(), "Idempotency-Key": "key-0000001"}
        ).status_code
        == 422
    )
    runtime.service = None
    assert _post(client).status_code == 503


def test_status_is_tenant_and_purpose_scoped(tmp_path, monkeypatch):
    client, _, _, _ = _client(tmp_path, monkeypatch)
    run_id = _post(client).json()["run_id"]
    url = f"/api/v2/analytics/runs/{run_id}"
    ok = client.get(url, params={"purpose": PURPOSE}, headers=_auth(user="viewer"))
    assert ok.status_code == 200 and ok.json()["outcome"]["outcome"] == "answer"
    assert client.get(url, params={"purpose": PURPOSE}, headers=_auth(tenant="tenant-b")).status_code == 404
    assert client.get(url, params={"purpose": "billing"}, headers=_auth(purposes=("billing",))).status_code == 404
    assert client.get(url, params={"purpose": "billing"}, headers=_auth()).status_code == 403
    assert client.get("/api/v2/analytics/runs/nope", params={"purpose": PURPOSE}, headers=_auth()).status_code == 404


def test_review_pause_requires_a_different_reviewer_and_then_answers(tmp_path, monkeypatch):
    client, rig, _, _ = _client(tmp_path, monkeypatch, threshold=1e-9)
    paused = _post(client)
    assert paused.status_code == 200 and paused.json()["state"] == "waiting_review"
    outcome = paused.json()["outcome"]
    assert outcome["outcome"] == "review" and outcome["allowed_actions"] == ["approve", "reject"]
    run_id = paused.json()["run_id"]
    review = rig.control.get_review(outcome["review_id"], tenant_id=TENANT, purpose=PURPOSE)
    decision = {"purpose": PURPOSE, "decision": "approved", "plan_fingerprint": review.plan_fingerprint}
    url = f"/api/v2/analytics/runs/{run_id}/review"
    own = client.post(url, json=decision, headers=_auth())
    assert own.status_code == 403 and own.json()["detail"] == "review_not_permitted"  # no self-approval
    stale = client.post(url, json={**decision, "plan_fingerprint": "0" * 64}, headers=_auth(user="reviewer"))
    assert stale.status_code == 409 and stale.json()["detail"] == "review_stale"
    approved = client.post(url, json=decision, headers=_auth(user="reviewer"))
    assert approved.status_code == 200 and approved.json()["outcome"]["outcome"] == "answer"
    again = client.post(url, json=decision, headers=_auth(user="reviewer"))
    assert again.status_code == 409 and again.json()["detail"] == "run_not_awaiting_review"


def test_rejected_review_is_a_refusal_without_execution(tmp_path, monkeypatch):
    client, rig, _, _ = _client(tmp_path, monkeypatch, threshold=1e-9)
    paused = _post(client).json()
    review = rig.control.get_review(paused["outcome"]["review_id"], tenant_id=TENANT, purpose=PURPOSE)
    done = client.post(
        f"/api/v2/analytics/runs/{paused['run_id']}/review",
        json={"purpose": PURPOSE, "decision": "rejected", "plan_fingerprint": review.plan_fingerprint},
        headers=_auth(user="reviewer"),
    )
    assert done.json()["outcome"]["outcome"] == "refuse" and "result" not in done.json()["outcome"]


def test_clarification_resumes_for_the_original_requester_only(tmp_path, monkeypatch):
    client, rig, _, _ = _client(tmp_path, monkeypatch, ambiguous=True)
    paused = _post(client).json()
    assert paused["state"] == "waiting_clarification" and paused["outcome"]["outcome"] == "clarify"
    question = paused["outcome"]["questions"][0]
    choice = question["choices"][0]["id"]
    url = f"/api/v2/analytics/runs/{paused['run_id']}/clarify"
    body = {"purpose": PURPOSE, "ambiguity_code": question["id"], "selected_id": choice}
    assert client.post(url, json=body, headers=_auth(user="intruder")).status_code == 403
    bogus = client.post(url, json={**body, "selected_id": "not-a-candidate"}, headers=_auth())
    assert bogus.status_code == 422 and bogus.json()["detail"] == "invalid_clarification"
    resumed = client.post(url, json=body, headers=_auth())
    assert resumed.status_code == 200, resumed.text
    # The fixture ontology keeps the reference ambiguous, so the two-turn limit must end the run.
    states = [resumed.json()["state"]]
    for _ in range(3):
        current = client.get(
            f"/api/v2/analytics/runs/{paused['run_id']}", params={"purpose": PURPOSE}, headers=_auth()
        ).json()
        if current["state"] != "waiting_clarification":
            break
        question = current["outcome"]["questions"][0]
        again = client.post(
            url,
            json={"purpose": PURPOSE, "ambiguity_code": question["id"], "selected_id": question["choices"][0]["id"]},
            headers=_auth(),
        )
        states.append(again.json()["state"] if again.status_code == 200 else str(again.status_code))
    assert states == ["waiting_clarification", "terminal"] and current["outcome"]["outcome"] == "refuse"
    assert rig.results._results == {}  # a run that never resolved its reference never executed
    late = client.post(url, json=body, headers=_auth())
    assert late.status_code == 409 and late.json()["detail"] == "run_not_awaiting_clarification"


def test_openapi_documents_the_endpoints_and_strict_bodies(tmp_path, monkeypatch):
    client, *_ = _client(tmp_path, monkeypatch)
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert set(paths) == {
        "/api/v2/analytics/analyze",
        "/api/v2/analytics/runs/{run_id}",
        "/api/v2/analytics/runs/{run_id}/clarify",
        "/api/v2/analytics/runs/{run_id}/review",
    }
    assert "post" in paths["/api/v2/analytics/analyze"] and "get" in paths["/api/v2/analytics/runs/{run_id}"]
    schemas = spec["components"]["schemas"]
    assert schemas["AnalyzeRequest"]["additionalProperties"] is False
    assert set(schemas["ReviewDecisionRequest"]["properties"]) >= {"decision", "plan_fingerprint"}
    assert "AnalyticsAnswerOutcome" in schemas and "AnalyticsReviewOutcome" in schemas


def test_default_app_router_is_inert_until_a_runtime_is_configured():
    from app.main import app

    response = TestClient(app).post(
        "/api/v2/analytics/analyze", json=BODY, headers={"Authorization": "Bearer x", "Idempotency-Key": "key-0000001"}
    )
    assert response.status_code == 503 and response.json()["detail"] == "governed_runtime_not_configured"
