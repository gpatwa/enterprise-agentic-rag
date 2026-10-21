"""ADS-065: one run traces across API, graph, context, gateway, and evidence; telemetry is redacted and correlated."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from reference_stack.stack import build_stack

from app.observability import (
    ATTRIBUTE_ALLOWLIST,
    LAYERS,
    REDACTED,
    Observability,
    Redactor,
    TracedEvidenceStore,
    TracedGateway,
    TracedService,
    run_ref,
    trace_id_for_run,
    traced_node,
)
from app.runtime.analyze_service import GovernedAnalyzeService, ServiceError

SERVICE = Path(__file__).resolve().parent.parent
PURPOSE = "analytics"
EMAIL = "jane.doe@example.com"
QUESTION = f"Show monthly revenue for {EMAIL}"


def _rig(tmp_path, name="a", **stack_kwargs):
    stack = build_stack("duckdb", tmp_path / name, **stack_kwargs)
    obs = Observability()
    stack.gateway = TracedGateway(stack.gateway, obs)
    stack.evidence = TracedEvidenceStore(stack.evidence, obs)
    original = stack.nodes
    stack.nodes = lambda identity, request, review_store=None: {
        node_id: traced_node(node_id, handler, obs)
        for node_id, handler in original(identity, request, review_store).items()
    }
    who = stack.verifier().verify(stack.token("requester"))
    return stack, TracedService(stack.service(), obs), obs, who


def _analyze(service, who, key="obs-key-0001", text=QUESTION):
    return service.analyze(who, purpose=PURPOSE, idempotency_key=key, request_text=text)


# ---- one run, one trace, five layers ----


def test_one_run_is_one_trace_across_api_graph_context_gateway_and_evidence(tmp_path):
    stack, service, obs, who = _rig(tmp_path)
    run = _analyze(service, who)
    assert run.state == "terminal" and run.outcome.outcome == "answer"
    trace_id = trace_id_for_run("tenant-a", run.run_id)
    spans = obs.tracer.trace(trace_id)
    assert {span.layer for span in spans} == set(LAYERS)
    assert {span.trace_id for span in obs.tracer.finished} == {trace_id}  # nothing outside this run's trace
    by_id = {span.span_id: span for span in spans}
    roots = [span for span in spans if span.parent_id is None]
    assert [span.name for span in roots] == ["api.analyze"]
    assert all(span.parent_id in by_id for span in spans if span.parent_id)  # a connected tree
    names = [span.name for span in spans]
    assert "context.retrieve" in names and "gateway.execute" in names and "evidence.seal" in names
    assert {"graph.bootstrap", "graph.policy", "graph.execute", "graph.result_validate", "graph.explain"} <= set(names)
    execute = next(s for s in spans if s.name == "graph.execute")
    gateway = next(s for s in spans if s.name == "gateway.execute")
    assert gateway.parent_id == execute.span_id  # the query ran under the node that asked for it
    assert next(s for s in spans if s.name == "evidence.seal").parent_id == roots[0].span_id
    assert gateway.attributes["row_count"] > 0 and gateway.attributes["dialect"] == "duckdb"
    assert all(span.ended_at is not None and span.duration_seconds >= 0 for span in spans)


def test_every_span_log_and_metric_correlates_to_the_run_without_naming_it(tmp_path):
    stack, service, obs, who = _rig(tmp_path)
    run = _analyze(service, who)
    ref = run_ref(run.run_id)
    node_spans = [s for s in obs.tracer.finished if s.layer in {"graph", "context"}]
    assert node_spans and all(s.attributes["run_ref"] == ref for s in node_spans)
    assert next(s for s in obs.tracer.finished if s.name == "api.analyze").attributes["run_ref"] == ref
    assert run.run_id not in obs.telemetry_text()  # correlation uses the reference, never the run ID
    assert any(f'"run_ref":"{ref}"' in line for line in obs.log.lines)
    trace_id = trace_id_for_run("tenant-a", run.run_id)
    assert any(f'"trace_id":"{trace_id}"' in line for line in obs.log.lines)


def test_a_run_that_pauses_and_resumes_stays_in_one_trace_across_requests(tmp_path):
    stack, service, obs, who = _rig(tmp_path, review_threshold=1e-9)
    paused = _analyze(service, who)
    assert paused.state == "waiting_review"
    review = stack.control.get_review(paused.outcome.review_id, tenant_id="tenant-a", purpose=PURPOSE)
    reviewer = stack.verifier().verify(stack.token("reviewer"))
    done = service.decide_review(
        reviewer,
        purpose=PURPOSE,
        run_id=paused.run_id,
        decision="approved",
        plan_fingerprint=review.plan_fingerprint,
        note=None,
    )
    assert done.state == "terminal" and done.outcome.reason_code == "unauthorized"  # the reviewer gets no rows
    assert service.status(who, purpose=PURPOSE, run_id=paused.run_id).outcome.outcome == "answer"
    trace = obs.tracer.trace(trace_id_for_run("tenant-a", paused.run_id))
    assert [s.name for s in trace if s.layer == "api"] == ["api.analyze", "api.review", "api.status"]
    assert {s.layer for s in trace} == set(LAYERS)
    assert len({s.trace_id for s in obs.tracer.finished}) == 1


def test_concurrent_runs_get_separate_traces_with_no_cross_parenting(tmp_path):
    stack, service, obs, who = _rig(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(lambda key: _analyze(service, who, key=key), ["obs-key-000A", "obs-key-000B"]))
    ids = {trace_id_for_run("tenant-a", run.run_id) for run in runs}
    assert len(ids) == 2 and {s.trace_id for s in obs.tracer.finished} == ids
    for trace_id in ids:
        spans = obs.tracer.trace(trace_id)
        by_id = {s.span_id: s for s in spans}
        assert all(s.parent_id is None or s.parent_id in by_id for s in spans)
        assert {s.layer for s in spans} == set(LAYERS)


# ---- redaction: nothing sensitive in any exported telemetry ----


def test_no_question_token_run_id_sql_row_value_or_physical_name_is_ever_exported(tmp_path):
    stack, service, obs, who = _rig(tmp_path)
    token = stack.token("requester")
    obs.redactor.register(token)
    run = _analyze(service, who)
    # A careless caller logging whatever it has is redacted as well.
    obs.log.emit(
        "info", f"debug dump for {EMAIL} with Bearer {token}", sql="SELECT amount FROM sales_orders", token=token
    )
    telemetry = obs.telemetry_text()
    for forbidden in (
        EMAIL,
        token,
        run.run_id,
        "SELECT",
        "sales_orders",
        "Show monthly",
        "policy_values",
        "@example.com",
        *[str(cell) for row in run.outcome.result.rows for cell in row if len(str(cell)) >= 5],
    ):
        assert forbidden not in telemetry, forbidden
    assert REDACTED in telemetry or "[SQL]" in telemetry


@pytest.mark.parametrize(
    ("text", "gone", "marker"),
    [
        ("auth eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl", "eyJhbGci", REDACTED),
        ("Authorization: Bearer abcdef0123456789xyz", "abcdef0123456789xyz", REDACTED),
        ("mail me at a.b+c@corp.example.org now", "a.b+c@corp", "[EMAIL]"),
        ("postgres://dbuser:S3cret!pw@db.internal:5432/x", "S3cret!pw", REDACTED),
        ("password=hunter2 and api_key: k-12345", "hunter2", REDACTED),
        ("ran SELECT id, amount FROM sales_orders WHERE x = 1", "sales_orders", "[SQL]"),
        ("DELETE FROM sales_orders WHERE 1=1", "sales_orders", "[SQL]"),
        ("with t as (select 1 from x) select * from t", "select 1", "[SQL]"),
    ],
)
def test_the_redactor_removes_each_class_of_sensitive_text(text, gone, marker):
    redacted = Redactor().text(text)
    assert gone not in redacted and marker in redacted


def test_registered_literals_long_text_and_structures_are_handled():
    redactor = Redactor(["CANARY-123456"])
    assert "CANARY" not in redactor.text("see CANARY-123456 here")
    assert redactor.text("x" * 500).endswith("...[truncated]") and len(redactor.text("x" * 500)) < 230
    assert redactor.value({"rows": [[1, 2]]}) == REDACTED and redactor.value([1]) == REDACTED
    assert redactor.value(7) == 7 and redactor.value(None) is None and redactor.value(True) is True
    assert redactor.mapping({"a": "p@q.example", "b": 1}) == {"a": "[EMAIL]", "b": 1}


def test_only_allow_listed_attributes_survive_and_the_rest_are_counted(tmp_path):
    obs = Observability()
    with obs.tracer.span(
        "probe", "api", op="analyze", request_text="Show revenue", sql="SELECT 1 FROM t", rows=[[1]]
    ) as span:
        obs.tracer.annotate(span, error_code="x", password="hunter2")
    (finished,) = obs.tracer.finished
    assert set(finished.attributes) <= ATTRIBUTE_ALLOWLIST and finished.dropped_attributes == 4
    assert "Show revenue" not in obs.telemetry_text() and "hunter2" not in obs.telemetry_text()


# ---- metrics ----


def test_metrics_count_requests_nodes_and_gateway_calls_and_expose_prometheus_text(tmp_path):
    stack, service, obs, who = _rig(tmp_path)
    _analyze(service, who)
    m = obs.metrics
    assert m.counter("analytics_requests_total", op="analyze", outcome="answer", tenant="tenant-a") == 1
    assert m.counter("analytics_node_total", node="execute", outcome="completed", layer="graph") == 1
    assert m.counter("analytics_node_total", node="retrieve", outcome="completed", layer="context") == 1
    assert m.counter("analytics_gateway_total", dialect="duckdb", outcome="ok") >= 2  # the query and its control query
    assert m.counter("analytics_evidence_sealed_total", outcome="succeeded") == 1
    assert m.samples("analytics_request_seconds", op="analyze") and all(
        v >= 0 for v in m.samples("analytics_node_seconds", node="policy")
    )
    text = m.exposition()
    assert 'analytics_requests_total{op="analyze",outcome="answer",tenant="tenant-a"} 1' in text
    assert "analytics_node_seconds_count" in text and "analytics_node_seconds_sum" in text
    assert "SELECT" not in text and QUESTION not in text


def test_metric_labels_are_allow_listed_and_cardinality_is_capped():
    obs = Observability()
    obs.metrics.inc("m", op="analyze", user_id="alice", run_id="r1")  # identifiers are not labels
    assert obs.metrics.counter("m", op="analyze") == 1 and obs.metrics.dropped_labels == 2
    for index in range(300):
        obs.metrics.inc("flood", tenant=f"tenant-{index}")
    assert len(obs.metrics._label_values["tenant"]) == 200
    assert obs.metrics.counter("flood", tenant="tenant-299") == 100  # the 100 values past the cap share one bucket
    assert obs.metrics.counter("flood", tenant="tenant-0") == 1 and 'tenant="other"' in obs.metrics.exposition()


# ---- failures are observable too, and observing changes nothing ----


def test_refusals_and_failures_are_visible_in_spans_metrics_and_logs(tmp_path):
    stack, service, obs, who = _rig(tmp_path, name="denied", denied=True)
    run = _analyze(service, who)
    assert run.outcome.outcome == "refuse"
    spans = obs.tracer.trace(trace_id_for_run("tenant-a", run.run_id))
    policy = next(s for s in spans if s.name == "graph.policy")
    assert policy.status == "error" and policy.attributes["error_code"] == "policy_denied"
    assert not [s for s in spans if s.layer == "gateway"]  # a refused run never touched the warehouse
    assert next(s for s in spans if s.name == "evidence.seal").attributes["terminal_kind"] == "refused"
    with pytest.raises(ServiceError):
        service.status(who, purpose="billing", run_id=run.run_id)
    refused = [s for s in obs.tracer.finished if s.name == "api.status"]
    assert refused[0].status == "error" and refused[0].attributes["error_code"] == "purpose_not_authorized"
    assert (
        obs.metrics.counter(
            "analytics_requests_total",
            op="status",
            outcome="error",
            error_code="purpose_not_authorized",
            tenant="tenant-a",
        )
        == 1
    )
    assert any('"event":"request_refused"' in line and "purpose_not_authorized" in line for line in obs.log.lines)


def test_a_gateway_failure_is_recorded_on_the_gateway_span(tmp_path):
    stack, service, obs, who = _rig(tmp_path, name="budget", max_cost_units=1e-6)
    run = _analyze(service, who)
    assert run.outcome.outcome == "failed"
    spans = obs.tracer.trace(trace_id_for_run("tenant-a", run.run_id))
    assert any(s.name == "gateway.estimate" and "cost_units" in s.attributes for s in spans)
    assert any(s.name == "graph.estimate" and s.status == "error" for s in spans)


def test_observing_a_run_changes_neither_its_answer_nor_its_evidence(tmp_path):
    plain_stack = build_stack("duckdb", tmp_path / "plain")
    plain = plain_stack.service().analyze(
        plain_stack.verifier().verify(plain_stack.token("requester")),
        purpose=PURPOSE,
        idempotency_key="obs-key-0001",
        request_text=QUESTION,
    )
    stack, service, obs, who = _rig(tmp_path, name="observed")
    observed = _analyze(service, who)
    assert observed.run_id == plain.run_id and observed.outcome.result == plain.outcome.result
    sealed = stack.evidence.get(observed.run_id, tenant_id="tenant-a", purpose=PURPOSE)
    plain_sealed = plain_stack.evidence.get(plain.run_id, tenant_id="tenant-a", purpose=PURPOSE)
    assert sealed.result.result_fingerprint == plain_sealed.result.result_fingerprint
    assert GovernedAnalyzeService.derive_run_id(who, PURPOSE, "obs-key-0001") == observed.run_id


def test_nothing_mounts_the_instrumentation_yet():
    for path in (SERVICE / "app/main.py", SERVICE / "app/api_v2.py"):
        assert "app.observability" not in path.read_text(), path.name
