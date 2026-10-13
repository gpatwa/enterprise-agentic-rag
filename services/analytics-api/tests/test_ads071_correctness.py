"""ADS-071: end-to-end correctness and PostgreSQL/DuckDB equivalence on the pinned ADS-070 corpus."""

from __future__ import annotations

import copy
import json

import pytest
from reference_stack import golden, m7_corpus
from reference_stack import m7_eval as m7
from reference_stack.golden import Observations, SuiteLockError, compute_metrics, evaluate, load_suite, run_engine

THRESHOLDS = json.loads(m7.E2E_THRESHOLDS.read_text())


def test_the_full_corpus_meets_the_proposed_gates_on_both_dialects():
    report = m7.run_correctness()
    assert report["engines"] == ["duckdb", "postgres"] and len(report["cases"]) == 200
    failed = [(c["engine"], c["case_id"], c["detail"]) for c in report["cases"] if not c["passed"]]
    assert not failed, failed
    assert report["ok"] and set(report["gates"]) == set(THRESHOLDS["gates"])
    assert report["gates"]["dialect_result_equivalence"]["value"] == 1.0 and report["samples"]["answered_runs"] == 120


def test_the_gates_are_the_plan_section_10_numbers_unchanged_and_nobody_approved_them():
    m4 = json.loads(golden.THRESHOLDS.read_text())
    assert {k: (v["op"], v["value"]) for k, v in THRESHOLDS["gates"].items()} == {
        k: (v["op"], v["value"]) for k, v in m4["gates"].items()
    }
    assert THRESHOLDS["approval"]["status"] == "proposed" and THRESHOLDS["approval"]["approved_by"] is None
    report = {"approval": THRESHOLDS["approval"], "corpus_approval": m7._corpus_approval()}
    assert report["corpus_approval"]["status"] == "proposed"


def test_the_thresholds_are_locked_to_the_corpus_digest():
    assert THRESHOLDS["corpus_sha256"] == m7_corpus.digest(m7_corpus.CORPUS.read_bytes())
    with pytest.raises(SuiteLockError):
        load_suite(m7_corpus.CORPUS, golden.THRESHOLDS)  # the M4 digest does not match this corpus
    load_suite(m7_corpus.CORPUS, m7.E2E_THRESHOLDS)


def test_a_wrong_expectation_for_a_p0_question_fails_the_p0_gate():
    suite, _ = load_suite(m7_corpus.CORPUS, m7.E2E_THRESHOLDS)
    broken = copy.deepcopy(suite)
    victim = next(c for c in broken["cases"] if c["kind"] == "answer" and c.get("p0"))
    victim["expect_rows"] = [["0"]] * len(victim["expect_rows"])
    obs = Observations()
    run_engine("duckdb", broken, obs)
    gates = evaluate(compute_metrics(broken, obs, ("duckdb",)), THRESHOLDS)
    assert not gates["p0_result_equivalence"]["meets"]
    assert any(not r.passed and r.case_id == victim["id"] for r in obs.cases)


def test_a_wrong_dialect_result_fails_equivalence():
    suite, _ = load_suite(m7_corpus.CORPUS, m7.E2E_THRESHOLDS)
    obs = Observations()
    run_engine("duckdb", suite, obs)
    run_engine("postgres", suite, obs)
    some = next(iter(obs.rows_by_case))
    obs.rows_by_case[some]["postgres"] = [["tampered"]]
    gates = evaluate(compute_metrics(suite, obs, ("duckdb", "postgres")), THRESHOLDS)
    assert not gates["dialect_result_equivalence"]["meets"]


def test_a_missed_refusal_fails_the_refusal_gate(monkeypatch):
    suite, _ = load_suite(m7_corpus.CORPUS, m7.E2E_THRESHOLDS)
    obs = Observations()
    run_engine("duckdb", suite, obs, only={"R001"})
    refusal = next(r for r in obs.cases if r.case_id == "R001")
    refusal.passed = False  # one missed refusal (an answer to "Tell me a joke") must fail the 100% gate
    gates = evaluate(compute_metrics(suite, obs, ("duckdb",)), THRESHOLDS)
    assert not gates["refusal_recall"]["meets"]


def test_the_rendered_report_does_not_claim_an_approval():
    text = m7.render_correctness(m7.run_correctness(("duckdb",)))
    assert (
        "not an approval" in text and "make analytics-m7-correctness" in text and "M4 `local_demo_review`" not in text
    )
