"""ADS-075: crash/replay, dependency failure, and chaos invariants, and proof that each fix and each gate can fail."""

from __future__ import annotations

import json

import pytest
from reference_stack import reliability_eval as ev

from app.execution.bridge import ExecutionResultStore
from app.runtime.governed_stages import PolicyValueStore

THRESHOLDS = json.loads(ev.THRESHOLDS.read_text())


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return ev.run_reliability(root=tmp_path_factory.mktemp("reliability"), chaos_runs=24)


def test_every_gate_is_met_and_the_thresholds_are_proposed(report):
    assert report["ok"], [(n, g["value"]) for n, g in report["gates"].items() if not g["meets"]]
    assert THRESHOLDS["approval"]["status"] == "proposed" and set(report["gates"]) == set(THRESHOLDS["gates"])


def test_a_worker_crash_at_every_node_before_or_after_still_ends_in_one_correct_execution(report):
    runs = report["same_process"]
    assert len(runs) == 26 and {(r["node"], r["when"]) for r in runs} == {
        (n, w) for n in ev.NODES for w in ("before", "after")
    }
    assert all(r["verdict"] == "correct_answer" and r["executions"] == 1 and r["chain_ok"] for r in runs)


def test_a_process_crash_either_recovers_or_fails_closed_and_never_returns_a_wrong_answer(report):
    runs = report["process_death_runs"]
    assert {r["verdict"] for r in runs} <= {"correct_answer", "typed_failure"}
    assert "policy-after" in report["process_death"]["recovered"]  # before the plan exists a new process can continue
    assert "execute-after" in report["process_death"]["failed_closed"]  # after it, process-local plans are gone
    assert all(r["executions"] <= 1 for r in runs)


def test_the_report_states_the_process_crash_limit_and_what_is_not_measured(report):
    text = ev.render_markdown(report)
    assert (
        "fail closed" in text
        and "Durable plan and result storage is not built" in text
        and "availability_percentage" in text
    )


def test_each_dependency_fails_into_a_typed_outcome(report):
    by_fault = {d["fault"]: d for d in report["dependencies"]}
    assert set(by_fault) == set(ev.DEPENDENCY_FAULTS)
    assert (
        by_fault["warehouse_down"]["code"] == "executor_unavailable"
        and by_fault["estimator_down"]["code"] == "executor_unavailable"
    )
    assert by_fault["context_snapshot_down"]["code"] == "context_unavailable"
    assert (
        by_fault["context_search_down"]["verdict"] == "typed_failure"
        and by_fault["model_timeout"]["code"] == "planner_unavailable"
    )
    assert by_fault["deadline_already_passed"]["code"] == "query_timeout"
    assert by_fault["explainer_down"]["verdict"] == "correct_answer" and by_fault["explainer_down"]["degraded"]
    assert all(d["executions"] == 0 for f, d in by_fault.items() if f not in {"warehouse_down", "explainer_down"})


def test_the_chaos_mix_is_seeded_and_repeatable(tmp_path):
    first = ev.chaos(tmp_path / "a", seed=7, runs=6)
    second = ev.chaos(tmp_path / "b", seed=7, runs=6)
    assert [r["plan"] for r in first] == [r["plan"] for r in second]
    assert [r["verdict"] for r in first] == [r["verdict"] for r in second]
    assert [r["plan"] for r in first] != [r["plan"] for r in ev.chaos(tmp_path / "c", seed=8, runs=6)]


# ---- the defects this evaluation found, and proof they stay fixed ----


def test_a_crash_after_the_side_effect_does_not_run_the_query_twice(tmp_path):
    result = ev._crash(tmp_path, "execute", "after", process_death=False)
    assert result["verdict"] == "correct_answer" and result["executions"] == 1


def test_a_crash_after_compiling_can_compile_again_on_resume(tmp_path):
    result = ev._crash(tmp_path, "compile", "after", process_death=False)
    assert result["verdict"] == "correct_answer"


def test_reverting_the_idempotent_execute_is_caught_as_a_duplicate_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(ExecutionResultStore, "has", lambda self, tenant_id, run_id, reference: False)
    result = ev._crash(tmp_path, "execute", "after", process_death=False)
    assert result["executions"] == 2  # the evaluation sees it; the duplicate-execution gate counts it


def test_reverting_the_non_consuming_policy_values_is_caught_as_a_failed_recovery(monkeypatch, tmp_path):
    def consuming_get(self, tenant_id, run_id, reference):
        with self._lock:
            try:
                return self._values.pop((tenant_id, run_id, reference))
            except KeyError as exc:
                raise LookupError("policy values are not scoped to this run") from exc

    monkeypatch.setattr(PolicyValueStore, "get", consuming_get)
    result = ev._crash(tmp_path, "compile", "after", process_death=False)
    assert result["verdict"] != "correct_answer"


def test_the_policy_value_store_is_bounded(monkeypatch):
    store = PolicyValueStore()
    monkeypatch.setattr(PolicyValueStore, "MAX_ENTRIES", 3)
    refs = [store.put("t", "r", {"i": i}) for i in range(5)]
    with pytest.raises(LookupError):
        store.get("t", "r", refs[0])
    assert store.get("t", "r", refs[-1]) == {"i": 4}
    store.discard("t", "r", refs[-1])
    with pytest.raises(LookupError):
        store.get("t", "r", refs[-1])


def test_a_wrong_answer_fails_the_wrong_answer_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ev, "EXPECTED_ROWS", [["1999-01-01", "1"]]
    )  # as if the system returned rows the oracle disagrees with
    report = ev.run_reliability(root=tmp_path, chaos_runs=1)
    assert (
        report["gates"]["wrong_answers"]["value"] > 0
        and not report["gates"]["wrong_answers"]["meets"]
        and not report["ok"]
    )


def test_a_month_bucket_returned_as_a_midnight_timestamp_is_still_the_correct_answer():
    from types import SimpleNamespace

    rows = [["2024-03-01T00:00:00", "1969"], ["2024-02-01T00:00:00", "1468"], ["2024-01-01T00:00:00", "563"]]
    response = SimpleNamespace(
        state="terminal", outcome=SimpleNamespace(outcome="answer", result=SimpleNamespace(rows=rows))
    )
    assert ev._classify(response, executions=1)["verdict"] == "correct_answer"
    wrong = SimpleNamespace(
        state="terminal",
        outcome=SimpleNamespace(outcome="answer", result=SimpleNamespace(rows=[["2024-03-01T00:00:00", "1"]])),
    )
    assert ev._classify(wrong, executions=1)["verdict"] == "wrong_answer"
