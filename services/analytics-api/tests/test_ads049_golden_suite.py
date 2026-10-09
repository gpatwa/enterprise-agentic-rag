"""ADS-049: the M4 golden suite meets the proposed thresholds, and can detect when it should not."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from reference_stack import golden
from reference_stack.golden import (
    Observations,
    SuiteLockError,
    compute_metrics,
    evaluate,
    load_suite,
    render_markdown,
    run_engine,
    run_golden,
)
from reference_stack.stack import RecordingGateway, build_stack

from app.compiler.postgres import CompiledQuery
from app.execution import ExecutionLimits

REPO = Path(__file__).resolve().parents[3]


def test_full_suite_meets_the_proposed_thresholds_on_both_dialects():
    report = run_golden()
    _, thresholds = load_suite()
    assert report["engines"] == ["duckdb", "postgres"] and len(report["cases"]) == 28
    assert set(report["gates"]) == set(thresholds["gates"])  # every proposed gate is measured
    failed = [(c["engine"], c["case_id"], c["detail"]) for c in report["cases"] if not c["passed"]]
    assert not failed, failed
    unmet = {name: gate for name, gate in report["gates"].items() if not gate["meets"]}
    assert report["meets_proposed_thresholds"] and not unmet, unmet
    assert report["samples"]["answered_runs"] == 12 and report["samples"]["latency"] == 60


def test_a_wrong_expected_result_is_detected_by_result_equivalence():
    suite, thresholds = load_suite()
    broken = copy.deepcopy(suite)
    next(c for c in broken["cases"] if c["id"] == "G01")["expect_rows"][0][1] = "1970"
    obs = Observations()
    run_engine("duckdb", broken, obs)
    gates = evaluate(compute_metrics(broken, obs, ("duckdb",)), thresholds)
    assert not gates["p0_result_equivalence"]["meets"]
    assert any(not r.passed and r.case_id == "G01" for r in obs.cases)


def test_executing_sql_the_compiler_did_not_produce_is_counted(tmp_path):
    stack = build_stack("duckdb", tmp_path)
    rogue = CompiledQuery(sql='SELECT COUNT(*) AS metric_0 FROM "sales_orders" AS d0', parameters={}, dialect="duckdb")
    RecordingGateway(stack.gateway, stack.executed_sql).execute(rogue, limits=ExecutionLimits())
    assert [sql for sql in stack.executed_sql if sql not in stack.compiled_sql] == [rogue.sql]


def test_the_corpus_is_locked_to_the_digest_the_thresholds_were_drafted_against(monkeypatch, tmp_path):
    tampered = tmp_path / "golden-suite-v1.json"
    tampered.write_bytes(golden.CORPUS.read_bytes() + b"\n")
    monkeypatch.setattr(golden, "CORPUS", tampered)
    with pytest.raises(SuiteLockError):
        load_suite()


def test_thresholds_are_proposed_not_approved_and_the_report_says_so():
    suite, thresholds = load_suite()
    assert thresholds["approval"]["status"] == "proposed"
    assert thresholds["approval"]["approved_by"] is None and thresholds["approval"]["approved_at"] is None
    markdown = render_markdown(run_golden(("duckdb",)))
    assert "PROPOSED and NOT APPROVED" in markdown and "not a gate pass" in markdown
    assert "dialect_result_equivalence" in markdown and "Not measured at M4" in markdown
    manifest = (REPO / "docs/execution/enterprise-analytics/agentic-data-stack-program.yaml").read_text()
    m4 = manifest.split("  M4:")[1].split("  M5:")[0]
    assert "human_gate_status: approved" not in m4  # the local_demo_review gate is never inferred


def test_expected_rows_match_an_independent_python_oracle():
    from datetime import datetime, timedelta

    rows = [
        (i, "refunded" if i % 5 == 0 else "paid", datetime(2024, 1, 1) + timedelta(hours=20 * i)) for i in range(1, 101)
    ]
    suite, _ = load_suite()
    expected = {c["id"]: c["expect_rows"] for c in suite["cases"] if c["kind"] == "answer"}
    by_status = {s: sum(i for i, st, _ in rows if st == s) for s in ("paid", "refunded")}
    assert expected["G02"] == [["paid", str(by_status["paid"])], ["refunded", str(by_status["refunded"])]]
    assert expected["G03"] == [[str(sum(i for i, _, _ in rows))]]
    monthly: dict[str, int] = {}
    for i, _, created in rows:
        monthly[created.strftime("%Y-%m-01")] = monthly.get(created.strftime("%Y-%m-01"), 0) + i
    assert expected["G05"] == [[k, str(v)] for k, v in sorted(monthly.items(), key=lambda kv: -kv[1])]
    json.dumps(expected)
