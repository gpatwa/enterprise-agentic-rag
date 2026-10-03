"""ADS-046: v1 response unchanged; the governed path cannot execute in shadow mode."""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_ads039_graph_adversarial import PURPOSE, TENANT, _database
from test_ads045_analyze_api import AUDIENCE, ISSUER, SECRET, Rig, _token

from app.runtime.shadow import (
    GovernedFacts,
    GovernedShadowAnalyzer,
    InMemoryShadowRecorder,
    ShadowRuntime,
    query_with_shadow,
    require_shadow_decision,
    shadow_nodes,
)
from app.security import OIDCVerifier
from packages.platform_contracts.analytics import AnalyticsQueryResponse
from packages.platform_contracts.routing import (
    RouteDecision,
    RoutingConfig,
    RoutingContext,
    RoutingRefusal,
    resolve_route,
)
from packages.platform_contracts.security import AnalyticsIdentity

CANARY = "canary-customer-4711"
QUESTION = f"Show monthly revenue for {CANARY}"
IDENTITY = AnalyticsIdentity(tenant_id=TENANT, user_id="requester", purposes=[PURPOSE], groups=["analyst"])


def _decision(mode="shadow", request_id="req-1"):
    return resolve_route(
        RoutingConfig(default_mode=mode), RoutingContext(tenant_id=TENANT, request_id=request_id, purpose=PURPOSE)
    )


def _legacy(status="succeeded"):
    ok = status == "succeeded"
    return AnalyticsQueryResponse(
        query_id="q1",
        query=QUESTION,
        dataset="olist",
        status=status,
        sql=f"SELECT month, SUM(x) FROM t WHERE c = '{CANARY}' GROUP BY 1" if ok else "",
        columns=["month", "revenue"] if ok else [],
        rows=[{"month": "2024-01", "revenue": f"{CANARY}-1"}] if ok else [],
        row_count=1 if ok else 0,
        error="" if ok else "boom",
    )


def _setup(tmp_path, monkeypatch, **rig_kwargs):
    control = _database(tmp_path, monkeypatch)
    rig = Rig(control, tmp_path, **rig_kwargs)
    executed = []
    real_execute = rig.gateway.execute
    rig.gateway.execute = lambda *a, **k: executed.append(1) or real_execute(*a, **k)
    analyzer = GovernedShadowAnalyzer(
        control, lambda identity, request, store: rig.nodes(identity, request, store), rig.new_state
    )
    return control, rig, analyzer, executed


def _run(decision, analyzer, sink, legacy=None, **kwargs):
    response = legacy or _legacy()

    async def call():
        return response

    return response, asyncio.run(
        query_with_shadow(
            call,
            decision=decision,
            identity=IDENTITY,
            purpose=PURPOSE,
            request_text=QUESTION,
            analyzer=analyzer,
            sink=sink,
            **kwargs,
        )
    )


def test_shadow_returns_the_v1_response_unchanged_and_records_a_privacy_safe_comparison(tmp_path, monkeypatch):
    control, rig, analyzer, executed = _setup(tmp_path, monkeypatch)
    sink = InMemoryShadowRecorder()
    original, returned = _run(_decision(), analyzer, sink)
    assert returned is original  # v1 response is the very same object
    record = sink.records[0]
    assert record["agreement"] == "both_answerable" and record["column_count_match"] is True
    assert record["governed"]["outcome"] == "plan_ready" and record["governed"]["plan_reference"]
    assert record["governed"]["metric_ids"] and record["governed_executed"] is False
    assert record["legacy"]["result_fingerprint"] and record["legacy"]["sql_fingerprint"]
    assert CANARY not in str(record) and "SELECT" not in str(record)  # no question, SQL, or row values
    assert executed == [] and rig.results._results == {}  # the warehouse was never queried


def test_blocked_nodes_replace_execution_even_when_the_factory_supplies_real_ones(tmp_path, monkeypatch):
    called = []
    nodes = {
        name: (lambda ni: called.append(ni.node_id))
        for name in ("approve", "execute", "result_validate", "explain", "plan")
    }
    out = shadow_nodes(nodes)
    assert out["plan"] is nodes["plan"]
    from datetime import datetime, timedelta, timezone

    from packages.platform_contracts.agent_runtime import NodeInput, RunBudget

    for name in ("approve", "execute", "result_validate", "explain"):
        node_input = NodeInput(
            run_id="r",
            tenant_id="t",
            purpose="p",
            node_id=name,
            state_version=1,
            context_snapshot_id="s",
            remaining_budget=RunBudget(deadline=datetime.now(timezone.utc) + timedelta(minutes=1)),
        )
        result = out[name](node_input)
        assert result.status == "failed" and result.error.code == "shadow_execution_blocked"
    assert called == []


def test_shadow_cannot_create_reviews_even_for_expensive_plans(tmp_path, monkeypatch):
    control, rig, analyzer, executed = _setup(tmp_path, monkeypatch, threshold=1e-9)
    sink = InMemoryShadowRecorder()
    _run(_decision(), analyzer, sink)
    assert sink.records[0]["governed"]["outcome"] == "review_required"
    with control.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM analytics_run_reviews")).scalar() == 0
    assert executed == []


def test_clarification_and_legacy_failure_are_classified(tmp_path, monkeypatch):
    control, rig, analyzer, executed = _setup(tmp_path, monkeypatch, ambiguous=True)
    sink = InMemoryShadowRecorder()
    _run(_decision(), analyzer, sink, legacy=_legacy("failed"))
    record = sink.records[0]
    assert record["governed"]["outcome"] == "clarify" and record["agreement"] == "neither"
    assert record["legacy"]["status"] == "failed" and record["legacy"]["result_fingerprint"] is None


def test_shadow_failures_timeouts_and_a_broken_sink_never_touch_the_response():
    class Boom:
        def analyze(self, *a, **k):
            raise RuntimeError("model down " + CANARY)

    class Slow:
        def analyze(self, *a, **k):
            time.sleep(0.5)

    sink = InMemoryShadowRecorder()
    original, returned = _run(_decision(), Boom(), sink)
    assert returned is original and sink.records[0]["governed"] == GovernedFacts(
        outcome="error", error_codes=["RuntimeError"]
    ).model_dump(mode="json")
    assert CANARY not in str(sink.records)
    sink2 = InMemoryShadowRecorder()
    _, returned = _run(_decision(), Slow(), sink2, timeout_seconds=0.05)
    assert sink2.records[0]["governed"]["outcome"] == "timeout"

    def broken(record):
        raise OSError("disk full")

    original, returned = _run(_decision(), Boom(), broken)
    assert returned is original


def test_routing_modes_gate_the_adapter():
    class Spy:
        calls = 0

        def analyze(self, *a, **k):
            Spy.calls += 1

    sink = InMemoryShadowRecorder()
    original, returned = _run(_decision("legacy"), Spy(), sink)
    assert returned is original and Spy.calls == 0 and sink.records == []
    with pytest.raises(RoutingRefusal):
        _run(_decision("disabled"), Spy(), sink)  # legacy is not even called
    for decision in (_decision("legacy"), _decision("disabled")):
        with pytest.raises(RoutingRefusal):
            require_shadow_decision(decision)
    governed = RouteDecision(
        tenant_id=TENANT,
        request_id="r",
        mode="governed",
        execute_legacy=False,
        execute_governed=True,
        record_shadow=False,
        audit_event_id="a",
    )
    with pytest.raises(RoutingRefusal):
        require_shadow_decision(governed)


def test_analyzer_rejects_mismatched_identity(tmp_path, monkeypatch):
    _, _, analyzer, executed = _setup(tmp_path, monkeypatch)
    other = AnalyticsIdentity(tenant_id="tenant-b", user_id="u", purposes=[PURPOSE])
    with pytest.raises(RoutingRefusal):
        analyzer.analyze(_decision(), other, purpose=PURPOSE, request_text=QUESTION)
    with pytest.raises(RoutingRefusal):
        analyzer.analyze(_decision(), IDENTITY, purpose="billing", request_text=QUESTION)
    assert executed == []


# ---- the real v1 endpoint ----


def _endpoint(tmp_path, monkeypatch, mode):
    from app import main

    control, rig, analyzer, executed = _setup(tmp_path, monkeypatch)
    calls = {"n": 0}
    legacy = _legacy()

    async def fake_query(request):
        calls["n"] += 1
        return legacy

    monkeypatch.setattr(main.analytics_service, "query", fake_query)
    runtime = ShadowRuntime(
        config=RoutingConfig(default_mode=mode),
        analyzer=analyzer,
        verifier=OIDCVerifier(ISSUER, AUDIENCE, {"k1": SECRET}, algorithms=("HS256",)),
    )
    monkeypatch.setattr(main, "shadow_runtime", runtime)
    return TestClient(main.app), runtime, legacy, calls, executed


def _post(client, headers):
    return client.post("/api/v1/analytics/query", json={"query": QUESTION}, headers=headers)


def test_v1_endpoint_response_is_identical_with_and_without_shadow(tmp_path, monkeypatch):
    client, runtime, legacy, calls, executed = _endpoint(tmp_path, monkeypatch, "shadow")
    auth = {"Authorization": f"Bearer {_token()}", "X-Analytics-Purpose": PURPOSE}
    shadowed = _post(client, auth)
    plain = _post(client, {})
    assert shadowed.status_code == 200 and shadowed.json() == plain.json() == legacy.model_dump(mode="json")
    assert len(runtime.sink.records) == 1 and calls["n"] == 2 and executed == []
    # Unverifiable, unauthorized, or legacy-routed callers fall back to plain v1 with no shadow work.
    for headers in (
        {"Authorization": "Bearer junk", "X-Analytics-Purpose": PURPOSE},
        {"Authorization": f"Bearer {_token()}", "X-Analytics-Purpose": "billing"},
        {"Authorization": f"Bearer {_token()}"},
    ):
        assert _post(client, headers).json() == plain.json()
    assert len(runtime.sink.records) == 1
    runtime.config = RoutingConfig(default_mode="legacy")
    _post(client, auth)
    assert len(runtime.sink.records) == 1


def test_v1_endpoint_is_untouched_by_default(monkeypatch):
    from app import main

    assert main.shadow_runtime.analyzer is None and main.shadow_runtime.decide("Bearer x", "p") is None
