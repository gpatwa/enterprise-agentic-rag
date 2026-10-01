"""ADS-041: fanout, missing groups, invalid totals, truncation, shape, grain, fingerprint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import duckdb
import pytest
from test_ads040_execution_gateways import _contract, _intent

from app.compiler import DuckDBCompilerAdapter
from app.compiler.postgres import CompiledQuery
from app.execution import (
    DuckDBGateway,
    ExecutionLimits,
    ExecutionResult,
    ExecutionResultStore,
    control_intent,
    result_fingerprint,
    run_control_totals,
    validate_result,
)
from app.runtime import result_validation_node
from app.runtime.governed_stages import CompiledPlanStore
from packages.platform_contracts.agent_runtime import NodeInput, RunBudget

GROUPED_SQL = (
    'SELECT d0."status" AS dimension_0, SUM(d0."amount") AS metric_0 FROM "sales_orders" AS d0 '
    "{where} GROUP BY 1 ORDER BY 2 DESC LIMIT 25"
)
FILTER = "WHERE d0.\"status\" IN ('paid', 'refunded')"


@pytest.fixture
def lake(tmp_path):
    connection = duckdb.connect()
    connection.execute("""
        CREATE TABLE sales_orders AS SELECT 'o' || i AS id, CAST(i AS DECIMAL(12,2)) AS amount,
            CASE WHEN i % 4 = 0 THEN 'refunded' WHEN i % 4 = 3 THEN 'cancelled' ELSE 'paid' END AS status,
            TIMESTAMP '2024-01-01' + INTERVAL (i) HOUR AS created_at FROM range(1, 101) t(i)""")
    connection.execute("""CREATE TABLE order_items AS
        SELECT 'o' || i AS order_id, 'sku' || k AS sku FROM range(1, 101) t(i), range(1, 4) u(k)""")
    for table in ("sales_orders", "order_items"):
        connection.execute(f"COPY {table} TO '{tmp_path / (table + '.parquet')}' (FORMAT PARQUET)")
    connection.close()
    return DuckDBGateway({t: tmp_path / f"{t}.parquet" for t in ("sales_orders", "order_items")}, allowed_root=tmp_path)


def _intent_wide():
    return _intent(
        time_range=None, filters=[{"field_id": "orders.status", "operator": "in", "values": ["paid", "refunded"]}]
    )


def _compile(intent, contract):
    return DuckDBCompilerAdapter().compile(intent, contract)


def _run(lake, sql, limits=None):
    plan = CompiledQuery(sql=sql, parameters={}, dialect="duckdb")
    return plan, lake.execute(plan, limits=limits or ExecutionLimits())


def _totals(lake, intent):
    return run_control_totals(intent, _contract(), compile_plan=_compile, gateway=lake, limits=ExecutionLimits())


def _codes(report):
    return set(report.blocking_codes)


def test_certified_grouped_result_reconciles_to_the_control_total(lake):
    intent, contract = _intent_wide(), _contract()
    plan = _compile(intent, contract)
    result = lake.execute(plan, limits=ExecutionLimits())
    totals = _totals(lake, intent)
    assert totals == {"revenue": Decimal("3775.00")}  # paid + refunded, independent of grouping
    report = validate_result(result, plan, intent, contract, control_totals=totals)
    assert report.status == "valid" and not report.issues
    assert {"shape", "grain", "sort", "reconciliation", "truncation"} <= set(report.checks)
    assert report.fingerprint == validate_result(result, plan, intent, contract, control_totals=totals).fingerprint


def test_join_fanout_is_detected(lake):
    intent, contract = _intent_wide(), _contract()
    sql = GROUPED_SQL.format(where='JOIN "order_items" AS i ON i.order_id = d0.id ' + FILTER)
    plan, result = _run(lake, sql)
    report = validate_result(result, plan, intent, contract, control_totals=_totals(lake, intent))
    assert report.status == "invalid" and _codes(report) == {"fanout_suspected"}


def test_missing_groups_are_detected(lake):
    intent, contract = _intent_wide(), _contract()
    plan, result = _run(lake, GROUPED_SQL.format(where="WHERE d0.\"status\" = 'paid'"))
    report = validate_result(result, plan, intent, contract, control_totals=_totals(lake, intent))
    assert _codes(report) == {"missing_groups_suspected"}


def test_truncation_is_blocking_and_skips_reconciliation(lake):
    intent, contract = _intent_wide(), _contract()
    plan = _compile(intent, contract)
    result = lake.execute(plan, limits=ExecutionLimits(max_rows=1))
    report = validate_result(result, plan, intent, contract, control_totals=_totals(lake, intent))
    assert _codes(report) == {"truncated_max_rows"}
    assert "reconciliation_skipped" in {issue.code for issue in report.issues}
    byte_limited = lake.execute(plan, limits=ExecutionLimits(max_bytes=5))
    assert "truncated_max_bytes" in _codes(validate_result(byte_limited, plan, intent, contract, control_totals={}))


def test_missing_control_total_blocks_unless_explicitly_optional(lake):
    intent, contract = _intent_wide(), _contract()
    plan = _compile(intent, contract)
    result = lake.execute(plan, limits=ExecutionLimits())
    assert _codes(validate_result(result, plan, intent, contract)) == {"reconciliation_missing"}
    relaxed = validate_result(result, plan, intent, contract, require_control_totals=False)
    assert relaxed.status == "valid_with_warnings" and relaxed.acceptable


def test_control_intent_drops_grouping_but_keeps_the_population():
    intent = _intent_wide()
    control = control_intent(intent)
    assert control.group_by == [] and control.sort == [] and control.limit == 1
    assert control.filters == intent.filters and control.metrics == intent.metrics


# ---- pure checks on hand-built results ----


def _result(columns, rows, **kwargs):
    return ExecutionResult(
        dialect="duckdb", columns=tuple(columns), rows=tuple(map(tuple, rows)), byte_count=1, **kwargs
    )


def _plan():
    return CompiledQuery(sql="SELECT 1", parameters={"p0": 1}, dialect="duckdb")


def _contract_with_metrics():
    base = _contract()
    grain = base.metrics[0].grain
    extra = [
        base.metrics[0].model_copy(update={"id": "peak", "aggregation": "max"}),
        base.metrics[0].model_copy(update={"id": "floor", "aggregation": "min"}),
        base.metrics[0].model_copy(update={"id": "typical", "aggregation": "average"}),
        base.metrics[0].model_copy(update={"id": "buyers", "aggregation": "count_distinct"}),
        base.metrics[0].model_copy(update={"id": "orders_n", "aggregation": "count", "measure_field_id": None}),
    ]
    assert grain
    return base.model_copy(update={"metrics": [*base.metrics, *extra]})


def _multi_intent(*metric_ids, **overrides):
    values = {"metrics": [{"metric_id": m} for m in metric_ids], "sort": [], "time_range": None, "filters": []}
    values.update(overrides)
    return _intent(**values)


def test_non_additive_totals_are_checked_against_their_bounds():
    contract = _contract_with_metrics()
    intent = _multi_intent("peak", "floor", "typical", "buyers")
    cols = ["dimension_0", "metric_0", "metric_1", "metric_2", "metric_3"]
    rows = [("a", 10, 1, 5, 4), ("b", 8, 2, 7, 3)]
    ok = {"peak": 10, "floor": 1, "typical": 6, "buyers": 5}
    assert validate_result(_result(cols, rows), _plan(), intent, contract, control_totals=ok).status == "valid"
    bad = {"peak": 11, "floor": 0, "typical": 9, "buyers": 8}
    report = validate_result(_result(cols, rows), _plan(), intent, contract, control_totals=bad)
    assert [i.code for i in report.issues] == ["invalid_total"] * 4
    below = {"peak": 10, "floor": 1, "typical": 6, "buyers": 3}  # fewer distinct than the largest group
    assert _codes(validate_result(_result(cols, rows), _plan(), intent, contract, control_totals=below)) == {
        "invalid_total"
    }


def test_count_metric_must_add_up_and_be_a_nonnegative_integer():
    contract = _contract_with_metrics()
    intent = _multi_intent("orders_n")
    cols = ["dimension_0", "metric_0"]
    assert _codes(
        validate_result(_result(cols, [("a", 3), ("b", 4)]), _plan(), intent, contract, control_totals={"orders_n": 9})
    ) == {"missing_groups_suspected"}
    assert _codes(
        validate_result(_result(cols, [("a", 3), ("b", 4)]), _plan(), intent, contract, control_totals={"orders_n": 6})
    ) == {"fanout_suspected"}
    for bad in (-1, 2.5, None, float("nan"), "7"):
        report = validate_result(_result(cols, [("a", bad)]), _plan(), intent, contract, control_totals={"orders_n": 1})
        assert "invalid_metric_value" in _codes(report), bad


def test_nonfinite_control_total_is_invalid():
    contract, intent = _contract(), _intent_wide()
    result = _result(["dimension_0", "metric_0"], [("a", 2), ("b", 1)])
    for total in (float("nan"), Decimal("Infinity"), "abc"):
        assert _codes(validate_result(result, _plan(), intent, contract, control_totals={"revenue": total})) == {
            "invalid_total"
        }


def test_shape_and_row_width_mismatches_are_detected():
    contract, intent = _contract(), _intent_wide()
    for columns, rows in (
        (["dimension_0"], [("a",)]),
        (["x", "y"], [("a", 1)]),
        (["dimension_0", "metric_0"], [("a",)]),
    ):
        assert _codes(
            validate_result(_result(columns, rows), _plan(), intent, contract, control_totals={"revenue": 1})
        ) == {"shape_mismatch"}


def test_duplicate_groups_and_ungrouped_cardinality_are_grain_violations():
    contract = _contract()
    grouped = _intent_wide()
    dup = _result(["dimension_0", "metric_0"], [("a", 1), ("a", 2)])
    assert "duplicate_group_keys" in _codes(
        validate_result(dup, _plan(), grouped, contract, control_totals={"revenue": 3})
    )
    ungrouped = _multi_intent("revenue", group_by=[])
    assert _codes(validate_result(_result(["metric_0"], [(1,), (2,)]), _plan(), ungrouped, contract)) == {
        "grain_cardinality"
    }
    assert _codes(validate_result(_result(["metric_0"], []), _plan(), ungrouped, contract)) == {"grain_cardinality"}
    assert validate_result(_result(["metric_0"], [(1,)]), _plan(), ungrouped, contract).status == "valid"


def test_limit_and_sort_contracts():
    contract = _contract()
    intent = _intent_wide()  # sort revenue desc, limit 25
    cols = ["dimension_0", "metric_0"]
    ascending = _result(cols, [("a", 1), ("b", 2)])
    assert _codes(validate_result(ascending, _plan(), intent, contract, control_totals={"revenue": 3})) == {
        "sort_violated"
    }
    with_nulls = _result(cols, [("a", 5), ("b", None), ("c", 1)])
    assert validate_result(with_nulls, _plan(), intent, contract, control_totals={"revenue": 6}).status == "valid"
    small = _intent_wide().model_copy(update={"limit": 2})
    full = validate_result(_result(cols, [("a", 2), ("b", 1)]), _plan(), small, contract, control_totals={"revenue": 3})
    assert full.status == "valid_with_warnings" and [i.code for i in full.issues] == [
        "limit_reached",
        "reconciliation_skipped",
    ]
    over = validate_result(_result(cols, [("a", 3), ("b", 2), ("c", 1)]), _plan(), small, contract)
    assert "limit_exceeded" in _codes(over)


def test_fingerprints_bind_data_plan_and_dialect():
    contract, intent = _contract(), _intent_wide()
    cols = ["dimension_0", "metric_0"]
    result = _result(cols, [("a", Decimal("2.50")), ("b", Decimal("1"))])
    same = _result(cols, [("a", Decimal("2.5")), ("b", Decimal("1.00"))])
    assert result_fingerprint(result) == result_fingerprint(same)  # numerically identical decimals
    assert result_fingerprint(result) != result_fingerprint(
        _result(cols, [("a", Decimal("2.51")), ("b", Decimal("1"))])
    )
    recorded = result_fingerprint(result)
    ok = validate_result(
        result, _plan(), intent, contract, control_totals={"revenue": Decimal("3.5")}, expected_fingerprint=recorded
    )
    assert ok.status == "valid"
    tampered = _result(cols, [("a", Decimal("9")), ("b", Decimal("1"))])
    assert "fingerprint_mismatch" in _codes(
        validate_result(
            tampered, _plan(), intent, contract, control_totals={"revenue": 10}, expected_fingerprint=recorded
        )
    )
    other = CompiledQuery(sql="SELECT 1", parameters={}, dialect="postgres")
    assert "dialect_mismatch" in _codes(
        validate_result(result, other, intent, contract, control_totals={"revenue": 3.5})
    )
    assert (
        ok.plan_fingerprint
        != validate_result(
            result,
            CompiledQuery(sql="SELECT 2", parameters={}, dialect="duckdb"),
            intent,
            contract,
            control_totals={"revenue": Decimal("3.5")},
        ).plan_fingerprint
    )


def test_report_details_never_contain_row_values():
    contract, intent = _contract(), _intent_wide()
    secret = _result(["dimension_0", "metric_0"], [("alice@example.com", 1), ("alice@example.com", 2)])
    report = validate_result(secret, _plan(), intent, contract, control_totals={"revenue": 99})
    assert report.issues and all("alice" not in issue.detail for issue in report.issues)


# ---- graph node ----


def _node(lake, plan, result, intent, controls):
    plans, results = CompiledPlanStore(), ExecutionResultStore()
    plan_ref = plans.put("tenant-a", "run-1", plan)
    result_ref = results.put("tenant-a", "run-1", plan_ref, result)
    contracts = SimpleNamespace(get_certified=lambda *_: SimpleNamespace(contract=_contract()))
    node_input = NodeInput(
        run_id="run-1",
        tenant_id="tenant-a",
        purpose="analysis",
        node_id="result_validate",
        state_version=3,
        context_snapshot_id="snap-1",
        payload={
            "intent": intent.model_dump(mode="json"),
            "compiled_plan_reference": plan_ref,
            "execution_reference": result_ref,
        },
        remaining_budget=RunBudget(deadline=datetime.now(timezone.utc) + timedelta(minutes=5)),
    )
    return result_validation_node(plans, results, contracts, controls), node_input


def test_node_passes_valid_results_to_explain_and_fails_invalid_ones(lake):
    intent = _intent_wide()
    controls = lambda ni, i, c: run_control_totals(i, c, compile_plan=_compile, gateway=lake, limits=ExecutionLimits())  # noqa: E731
    plan = _compile(intent, _contract())
    handler, node_input = _node(lake, plan, lake.execute(plan, limits=ExecutionLimits()), intent, controls)
    output = handler(node_input)
    assert output.status == "completed" and output.next_node == "explain" and output.evidence[0].kind == "decision"

    fan_plan, fan_result = _run(
        lake, GROUPED_SQL.format(where='JOIN "order_items" AS i ON i.order_id = d0.id ' + FILTER)
    )
    handler, node_input = _node(lake, fan_plan, fan_result, intent, controls)
    failed = handler(node_input)
    assert failed.status == "failed" and failed.error.code == "result_invalid"
    assert "fanout_suspected" in failed.error.message_reference


def test_node_fails_closed_when_the_control_query_or_inputs_fail(lake):
    intent = _intent_wide()
    plan = _compile(intent, _contract())
    result = lake.execute(plan, limits=ExecutionLimits())

    def broken(*_):
        raise RuntimeError("warehouse down")

    handler, node_input = _node(lake, plan, result, intent, broken)
    assert handler(node_input).error.code == "control_query_failed"
    handler, node_input = _node(lake, plan, result, intent, lambda *_: {})
    missing = node_input.model_copy(update={"payload": {**node_input.payload, "execution_reference": "nope"}})
    assert handler(missing).error.code == "result_inputs_unavailable"
    foreign = node_input.model_copy(update={"tenant_id": "tenant-b"})
    assert handler(foreign).error.code == "result_inputs_unavailable"
