"""ADS-077: provider variance, degraded mode, and rollback are bounded and reproducible, and each gate can fail."""

from __future__ import annotations

import json
from unittest import mock

import pytest
from reference_stack import provider_eval as ev

THRESHOLDS = json.loads(ev.THRESHOLDS.read_text())


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return ev.run_provider_evaluation(root=tmp_path_factory.mktemp("provider"))


def test_every_gate_is_met_and_the_thresholds_are_proposed(report):
    assert report["ok"], [(n, g["value"]) for n, g in report["gates"].items() if not g["meets"]]
    assert THRESHOLDS["approval"]["status"] == "proposed" and set(report["gates"]) == set(THRESHOLDS["gates"])


def test_the_same_intent_in_a_different_wire_format_gives_the_same_fingerprint(report):
    baseline = {r["question"]: r["fingerprint"] for r in report["runs"] if r["mode"] == "baseline"}
    assert all(baseline.values())
    for mode in ev.EQUIVALENT:
        runs = [r for r in report["runs"] if r["mode"] == mode]
        assert len(runs) == len(ev.QUESTIONS) and all(
            r["correct"] and r["fingerprint"] == baseline[r["question"]] for r in runs
        )


def test_nonconforming_provider_output_ends_in_a_typed_failure_with_no_query_and_one_call(report):
    for mode in ev.NONCONFORMING:
        runs = [r for r in report["runs"] if r["mode"] == mode]
        assert runs and all(
            r["kind"] == "failed" and r["code"] == "planner_unavailable" and r["executions"] == 0 and r["calls"] == 1
            for r in runs
        ), mode


def test_a_changed_label_case_never_answers_wrongly(report):
    runs = [r for r in report["runs"] if r["mode"] in ev.TOLERATED]
    assert runs and all(
        r["correct"] in (True, None) for r in runs
    )  # resolved by the certified ontology by design, or a typed failure


def test_a_provider_that_is_down_fails_every_request_safely_and_quickly(report):
    degraded = report["samples"]["degraded"]
    assert degraded["unsafe"] == 0 and degraded["codes"] == ["planner_unavailable"] and degraded["max_calls"] == 1
    assert degraded["seconds"] < 30


def test_ungrounded_explainer_claims_never_reach_the_caller_and_the_rows_stay_correct(report):
    assert len(report["explainers"]) == 3
    assert all(
        e["status"] == "evidence_only" and e["claims_shown"] == 0 and e["rows_correct"] for e in report["explainers"]
    )


def test_pinned_prompts_reproduce_and_a_rollback_restores_the_earlier_fingerprints(report):
    assert (
        report["samples"]["reproducibility"]["rate"] == 1.0 and report["samples"]["reproducibility"]["comparisons"] == 4
    )


def test_the_report_states_what_it_does_not_show(report):
    text = ev.render_markdown(report)
    assert "not how a real provider behaves" in text.replace(
        "**this shows the pipeline's bounds, not how a real provider behaves.**", "not how a real provider behaves"
    )
    assert "valid_but_wrong_intent" in text and "retry_and_circuit_breaking" in text and "NOT APPROVED" in text


def test_a_provider_whose_wire_format_changes_the_answer_fails_the_agreement_gate(tmp_path):
    original = ev._Provider.distort

    def corrupting(self, reply):
        out = original(self, reply)
        if self.mode == "reordered_keys":
            return {**out, "limit": 1}  # reordering that also alters the intent
        return out

    with mock.patch.object(ev._Provider, "distort", corrupting):
        runs = ev.provider_variance(tmp_path)
    baseline = {r["question"]: r["fingerprint"] for r in runs if r["mode"] == "baseline"}
    changed = [r for r in runs if r["mode"] == "reordered_keys" and r["fingerprint"] != baseline[r["question"]]]
    assert changed


def test_a_provider_output_that_gets_answered_wrongly_is_counted_as_a_wrong_answer(monkeypatch, tmp_path):
    monkeypatch.setitem(ev.QUESTIONS, "What is total revenue", [["1"]])
    run = ev._ask(tmp_path, "baseline", "What is total revenue", key="wrong-key-000001")
    assert run["correct"] is False


def test_a_retry_storm_would_fail_the_bounded_failure_gate(report):
    gate = THRESHOLDS["gates"]["model_calls_per_failing_run_max"]
    assert report["gates"]["model_calls_per_failing_run_max"]["value"] == 1
    assert not ev._OPS[gate["op"]](3, gate["value"])  # a client that retried twice (3 calls) would not meet the gate
