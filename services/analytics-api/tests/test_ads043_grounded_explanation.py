"""ADS-043: claims cite fixed result/semantic IDs; the repair step cannot alter the result."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import test_ads041_result_validation as _ads041
from test_ads040_execution_gateways import _contract
from test_ads041_result_validation import _compile, _intent_wide

from app.execution import (
    DraftClaim,
    ExecutionLimits,
    ExecutionResult,
    ExecutionResultStore,
    build_fact_sheet,
    explain_result,
    result_fingerprint,
    verify_claims,
    visualization_spec,
)
from app.runtime import ExplanationStore, explain_node
from app.runtime.governed_stages import CompiledPlanStore
from packages.platform_contracts.agent_runtime import NodeInput, RunBudget

lake = _ads041.lake  # reuse the DuckDB lake fixture


def _result(rows, columns=("dimension_0", "metric_0")):
    return ExecutionResult(dialect="duckdb", columns=columns, rows=tuple(rows), byte_count=10)


ROWS = [("paid", Decimal("1200.50")), ("refunded", Decimal("300"))]


def _sheet():
    return build_fact_sheet(_result(ROWS), _intent_wide(), _contract())


def test_fact_sheet_addresses_cells_and_semantic_ids_without_changing_the_result():
    result = _result(ROWS)
    sheet = build_fact_sheet(result, _intent_wide(), _contract())
    assert sheet.result_fingerprint == result_fingerprint(result)
    assert sheet.get("cell:r0c1").value == "1200.5" and sheet.get("cell:r1c0").value == "refunded"
    assert sheet.get("metric:revenue") and sheet.get("contract:sales-core@v1")
    assert sheet.get("cell:r9c9") is None


def test_grounded_claims_pass_and_ungrounded_ones_are_named_without_values():
    sheet = _sheet()
    good = DraftClaim("Paid orders brought in 1,200.5.", ("cell:r0c0", "cell:r0c1", "metric:revenue"))
    assert verify_claims(sheet, [good]) == ()
    cases = {
        "claim_0:uncited": DraftClaim("Revenue grew.", ()),
        "claim_0:unknown_citation": DraftClaim("Revenue is 5.", ("cell:r7c7",)),
        "claim_0:no_result_cell": DraftClaim("Revenue matters.", ("metric:revenue",)),
        "claim_0:ungrounded_number": DraftClaim("Paid brought in 9999.", ("cell:r0c1",)),
        "claim_0:bad_text": DraftClaim("  ", ("cell:r0c1",)),
    }
    for code, claim in cases.items():
        assert verify_claims(sheet, [claim]) == (code,)
    assert verify_claims(sheet, []) == ("no_claims",)


def test_a_number_must_come_from_a_cited_cell_not_just_any_cell():
    claim = DraftClaim("Refunded was 1200.5.", ("cell:r1c0", "cell:r1c1"))
    assert verify_claims(_sheet(), [claim]) == ("claim_0:ungrounded_number",)


def test_repair_gets_the_violations_and_may_fix_prose_once():
    seen = []

    def explainer(sheet, violations):
        seen.append(violations)
        number = "9999" if not violations else "1200.50"
        return [DraftClaim(f"Paid was {number}.", ("cell:r0c1",))]

    result = _result(ROWS)
    explanation = explain_result(result, _intent_wide(), _contract(), explainer)
    assert explanation.status == "grounded" and explanation.attempts == 2
    assert seen == [(), ("claim_0:ungrounded_number",)]
    assert explanation.result_fingerprint == result_fingerprint(result)


def test_failed_repair_returns_evidence_without_prose():
    explainer = lambda sheet, violations: [DraftClaim("Paid was 1.", ("cell:r0c1",))]  # noqa: E731
    result = _result(ROWS)
    explanation = explain_result(result, _intent_wide(), _contract(), explainer)
    assert explanation.status == "evidence_only" and explanation.claims == ()
    assert explanation.attempts == 2 and explanation.violations
    assert explanation.visualization.kind == "bar"  # evidence (chart + result) still returned
    assert explanation.result_fingerprint == result_fingerprint(result)


def test_explainer_errors_degrade_to_evidence_only():
    def boom(sheet, violations):
        raise TimeoutError("model unavailable")

    explanation = explain_result(_result(ROWS), _intent_wide(), _contract(), boom)
    assert explanation.status == "evidence_only"
    assert explanation.violations == ("explainer_error:TimeoutError",)


def test_result_mutation_during_explanation_is_detected():
    result = _result(ROWS)
    original = result.rows

    def tamper(sheet, violations):
        object.__setattr__(result, "rows", (("paid", Decimal("1")),))  # simulates a hostile explainer
        return [DraftClaim("Paid was 1.", ("cell:r0c1",))]

    from app.execution import ExplanationIntegrityError

    with pytest.raises(ExplanationIntegrityError):
        explain_result(result, _intent_wide(), _contract(), tamper)
    assert original == tuple(ROWS)


def test_visualization_spec_is_deterministic_from_intent_shape_and_holds_no_data():
    base = _intent_wide()
    assert visualization_spec(base).kind == "bar"
    spec = visualization_spec(base)
    assert spec.x.semantic_id == base.group_by[0].dimension_id and spec.y[0].semantic_id == "revenue"
    assert spec.y[0].column_index == 1
    ungrouped = base.model_copy(update={"group_by": [], "sort": []})
    assert visualization_spec(ungrouped).kind == "stat"
    temporal = base.model_copy(
        update={"group_by": [base.group_by[0].model_copy(update={"time_granularity": "month"})], "sort": []}
    )
    assert visualization_spec(temporal).kind == "line"
    two = base.model_copy(
        update={"group_by": base.group_by * 1 + [base.group_by[0].model_copy(update={"dimension_id": "x"})], "sort": []}
    )
    assert visualization_spec(two).kind == "table"


# ---- graph node, real DuckDB result ----


def _node(lake, explainer, *, plan=None, result=None):
    intent = _intent_wide()
    plan = plan or _compile(intent, _contract())
    result = result or lake.execute(plan, limits=ExecutionLimits())
    plans, results, store = CompiledPlanStore(), ExecutionResultStore(), ExplanationStore()
    plan_ref = plans.put("tenant-a", "run-1", plan)
    result_ref = results.put("tenant-a", "run-1", plan_ref, result)
    contracts = SimpleNamespace(get_certified=lambda *_: SimpleNamespace(contract=_contract()))
    node_input = NodeInput(
        run_id="run-1",
        tenant_id="tenant-a",
        purpose="analysis",
        node_id="explain",
        state_version=4,
        context_snapshot_id="snap-1",
        payload={
            "intent": intent.model_dump(mode="json"),
            "compiled_plan_reference": plan_ref,
            "execution_reference": result_ref,
        },
        remaining_budget=RunBudget(deadline=datetime.now(timezone.utc) + timedelta(minutes=5)),
    )
    return explain_node(results, contracts, plans, explainer, store), node_input, store, result


def _faithful(sheet, violations):
    return [
        DraftClaim(
            f"{sheet.get('cell:r0c0').value} has {sheet.get('cell:r0c1').value} revenue.",
            ("cell:r0c0", "cell:r0c1", "metric:revenue"),
        )
    ]


def test_node_stores_a_grounded_explanation_and_binds_it_with_evidence(lake):
    handler, node_input, store, result = _node(lake, _faithful)
    output = handler(node_input)
    assert output.status == "completed" and output.next_node == "terminal"
    explanation = store.get("tenant-a", "run-1")
    assert explanation.status == "grounded" and explanation.result_fingerprint == result_fingerprint(result)
    assert output.evidence[0].fingerprint == explanation.fingerprint and output.evidence[0].kind == "decision"
    with pytest.raises(LookupError):
        store.get("tenant-b", "run-1")


def test_node_degrades_to_evidence_only_but_still_completes(lake):
    handler, node_input, store, _ = _node(lake, lambda s, v: [DraftClaim("Revenue is 42.", ("cell:r0c1",))])
    assert handler(node_input).status == "completed"
    assert store.get("tenant-a", "run-1").status == "evidence_only"


def test_node_refuses_to_explain_a_truncated_or_foreign_result(lake):
    plan = _compile(_intent_wide(), _contract())
    cut = ExecutionResult("duckdb", ("dimension_0", "metric_0"), (("paid", 1),), 1, True, "max_rows")
    handler, node_input, store, _ = _node(lake, _faithful, plan=plan, result=cut)
    failed = handler(node_input)
    assert failed.status == "failed" and failed.error.code == "explain_result_invalid"
    with pytest.raises(LookupError):
        store.get("tenant-a", "run-1")
    handler, node_input, *_ = _node(lake, _faithful)
    bad = node_input.model_copy(update={"payload": {**node_input.payload, "execution_reference": "nope"}})
    assert handler(bad).error.code == "explain_inputs_unavailable"


def test_real_graph_run_ends_with_a_grounded_explanation_bound_to_the_validated_result(tmp_path, monkeypatch):
    from test_ads042_evidence_envelope import _database, _real_answer_runner, _state

    control = _database(tmp_path, monkeypatch)
    store = ExplanationStore()

    def total(sheet, violations):
        return [DraftClaim(f"First value is {sheet.get('cell:r0c1').value}.", ("cell:r0c1", "metric:revenue"))]

    runner, plans, results, *_ = _real_answer_runner(
        control, tmp_path, explain=lambda p, r, c: explain_node(r, c, p, total, store)
    )
    state = runner.start(_state("real"), owner_id="w", lease_token="lease-real").state
    assert state.terminal_outcome.kind == "succeeded", (state.errors, state.current_node)
    explanation = store.get(state.tenant_id, state.run_id)
    result = results.get(state.tenant_id, state.run_id, state.execution_reference)
    assert explanation.status == "grounded" and explanation.result_fingerprint == result_fingerprint(result)
    assert explanation.fingerprint in {e.fingerprint for e in state.terminal_outcome.evidence} | {
        e.fingerprint for e in state.evidence
    }
