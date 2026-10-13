"""ADS-058: drift monitors for context, retrieval, intent, outcomes, latency, and cost."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from reference_stack import drift_eval
from reference_stack.drift_eval import T0, load_policy, make_window

from app.drift import (
    REQUIRED_RUNBOOK_SECTIONS,
    InMemoryAlertSink,
    deliver,
    evaluate_drift,
    outcome_distribution,
    runbook_path,
    runbook_problems,
    total_variation_distance,
)
from app.drift.monitors import _p95
from packages.platform_contracts.drift import DriftPolicy, DriftRule, RunObservation

SERVICE = Path(__file__).resolve().parent.parent
POLICY = load_policy()
BASE = {"n": 100, "refused": 0.2, "items": 6, "latency_ms": 1000, "cost": 1.0, "max_age_hours": 10}


def _alerts(baseline: dict, current: dict, policy: DriftPolicy = POLICY) -> list[str]:
    report = evaluate_drift(make_window(baseline), make_window(current, start=T0 + timedelta(days=1)), policy)
    return sorted(alert.rule_id for alert in report.alerts)


# ---- contract and policy ----


def test_the_repository_policy_is_valid_complete_and_not_approved():
    assert POLICY.approval.status == "proposed" and POLICY.approval.approved_by is None
    assert {rule.monitor for rule in POLICY.rules} == {"context", "retrieval", "intent", "outcomes", "latency", "cost"}
    assert len({rule.rule_id for rule in POLICY.rules}) == len(POLICY.rules)
    assert all(rule.runbook_id == f"drift-{rule.monitor}" for rule in POLICY.rules)


def test_a_policy_must_be_coherent():
    rule = POLICY.rules[0]
    with pytest.raises(ValidationError, match="unique"):
        DriftPolicy(policy_version="v", rules=(rule, rule), approval=POLICY.approval)
    wrong = rule.model_copy(update={"rule_id": "Z-99", "runbook_id": "drift-cost"})
    with pytest.raises(ValidationError, match="runbook"):
        DriftPolicy(policy_version="v", rules=(wrong,), approval=POLICY.approval)
    with pytest.raises(ValidationError, match="who approved"):
        DriftPolicy(policy_version="v", rules=(rule,), approval={"status": "approved"})
    with pytest.raises(ValidationError):
        DriftRule.model_validate({**rule.model_dump(), "threshold": 0})
    with pytest.raises(ValidationError, match="timezone"):
        RunObservation(run_id="r", tenant_id="t", observed_at=datetime(2026, 1, 1), outcome="succeeded")


def test_an_observation_carries_numbers_and_codes_only():
    fields = set(RunObservation.model_fields)
    assert fields.isdisjoint({"request_text", "sql", "rows", "intent", "note", "reason", "correction"})
    with pytest.raises(ValidationError):
        RunObservation.model_validate(
            {"run_id": "r", "tenant_id": "t", "observed_at": T0, "outcome": "succeeded", "request_text": "secret"}
        )


# ---- statistics and rules ----


def test_statistics_are_exact_and_deterministic():
    assert _p95([float(i) for i in range(1, 101)]) == 95.0 and _p95([7.0]) == 7.0 and _p95([]) is None
    left, right = {"a": 0.5, "b": 0.5}, {"a": 0.5, "c": 0.5}
    assert total_variation_distance(left, right) == 0.5 and total_variation_distance(left, left) == 0.0
    window = make_window({**BASE, "stale": 0.2, "clarify": 0.1})
    assert outcome_distribution(window) == {
        "review_required": 0.2,
        "clarification_required": 0.1,
        "refused": 0.2,
        "succeeded": 0.5,
    }
    assert make_window(BASE) == make_window(BASE)  # no randomness anywhere


def test_each_monitor_trips_its_own_rule_and_nothing_else():
    cases = {
        "C-01": {"stale": 0.2, "refused": 0.0},
        "C-02": {"max_age_hours": 96},
        "R-01": {"empty_retrieval": 0.2},
        "R-02": {"items": 3},
        "I-01": {"malformed": 0.1, "refused": 0.1},
        "I-02": {"clarify": 0.2, "refused": 0.0},
        "L-01": {"latency_ms": 1600},
        "K-01": {"cost": 1.6},
    }
    for expected, change in cases.items():
        assert _alerts(BASE, {**BASE, **change}) == [expected], expected
    mix = {**BASE, "refused": 0.5}
    assert _alerts(mix, {**mix, "refused": 0.0, "failed": 0.5}) == ["O-01"]
    good = {**BASE, "refused": 0.1}
    assert _alerts(good, {**good, "refused": 0.25}) == ["O-02"]


def test_thresholds_are_inclusive_and_improvements_never_alert():
    assert _alerts(BASE, {**BASE, "latency_ms": 1490}) == [] and _alerts(BASE, {**BASE, "latency_ms": 1500}) == ["L-01"]
    assert _alerts(BASE, {**BASE, "stale": 0.09, "refused": 0.11}) == []
    assert _alerts(BASE, {**BASE, "stale": 0.10, "refused": 0.10}) == ["C-01"]
    better = {**BASE, "refused": 0.0, "latency_ms": 100, "cost": 0.1, "items": 20}
    assert _alerts({**BASE, "refused": 0.1}, better) == []


def test_too_little_data_or_a_zero_baseline_is_skipped_not_guessed():
    report = evaluate_drift(make_window(BASE), make_window({**BASE, "n": 29, "latency_ms": 9_000, "cost": 9.0}), POLICY)
    assert report.alerts == () and {s.reason for s in report.skipped} == {"insufficient_data"}
    assert len(report.skipped) == len(POLICY.rules)
    at_minimum = evaluate_drift(make_window(BASE), make_window({**BASE, "n": 30, "latency_ms": 9_000}), POLICY)
    assert [a.rule_id for a in at_minimum.alerts] == ["L-01"]
    zero = evaluate_drift(make_window({**BASE, "cost": 0.0}), make_window({**BASE, "cost": 1.0}), POLICY)
    assert zero.alerts == () and [s.reason for s in zero.skipped] == ["baseline_zero"]
    empty = evaluate_drift((), (), POLICY)
    assert empty.alerts == () and len(empty.skipped) == len(POLICY.rules)


def test_alerts_carry_severity_runbook_and_the_numbers_behind_them():
    report = evaluate_drift(make_window(BASE), make_window({**BASE, "latency_ms": 2000}), POLICY)
    (alert,) = report.alerts
    assert (alert.rule_id, alert.severity, alert.runbook_id, alert.comparison) == (
        "L-01",
        "warning",
        "drift-latency",
        "ratio",
    )
    assert alert.current_value / alert.baseline_value == pytest.approx(2.0) and alert.threshold == 1.5
    assert alert.baseline_samples == alert.current_samples == 100
    assert report.policy_status == "proposed"
    critical = evaluate_drift(make_window(BASE), make_window({**BASE, "stale": 0.3, "refused": 0.0}), POLICY).alerts[0]
    assert critical.severity == "critical"


def test_reports_are_reproducible_and_delivery_only_emits():
    one = evaluate_drift(make_window(BASE), make_window({**BASE, "cost": 3.0}), POLICY)
    two = evaluate_drift(make_window(BASE), make_window({**BASE, "cost": 3.0}), POLICY)
    assert one == two
    sink = InMemoryAlertSink()
    assert deliver(one, sink) is one and sink.alerts == list(one.alerts) and len(sink.alerts) == 1


# ---- runbooks ----


def test_every_rule_points_at_a_runbook_with_the_required_sections():
    for rule in POLICY.rules:
        assert runbook_path(rule.runbook_id).is_file(), rule.runbook_id
        assert runbook_problems(rule.runbook_id) == []
    assert runbook_problems("drift-nonexistent")
    for section in REQUIRED_RUNBOOK_SECTIONS:
        assert section in runbook_path("drift-cost").read_text()
    assert "Do not" in runbook_path("drift-intent").read_text()


def test_a_runbook_missing_a_section_is_reported(tmp_path):
    (tmp_path / "drift-x.md").write_text("# x\n\n## Symptom\n\nonly this\n")
    problems = runbook_problems("drift-x", tmp_path)
    assert len(problems) == len(REQUIRED_RUNBOOK_SECTIONS) - 1


# ---- real runs, read-only, unwired ----


def test_observations_are_extracted_from_real_runs_without_writing(tmp_path):
    from reference_stack import triage_eval
    from sqlalchemy import text

    from app.drift import collect_observations

    stack, run = triage_eval._scenario("answer", tmp_path / "answer")
    refused, _ = triage_eval._scenario("policy_denied", tmp_path / "denied")

    def snapshot(s):
        with s.control.engine.connect() as connection:
            return [
                connection.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                for t in ("analytics_agent_runs", "analytics_evidence_envelopes", "analytics_run_transitions")
            ]

    before = snapshot(stack)
    far = datetime(2100, 1, 1, tzinfo=timezone.utc)
    (obs,) = collect_observations(
        stack.control.engine, "tenant-a", since=datetime(2000, 1, 1, tzinfo=timezone.utc), until=far
    )
    assert obs.run_id == run["run_id"] and obs.outcome == "succeeded" and obs.error_codes == ()
    assert obs.context_items and obs.context_items > 0 and obs.cost_units is not None and obs.latency_ms >= 0
    assert snapshot(stack) == before
    (denied,) = collect_observations(
        refused.control.engine, "tenant-a", since=datetime(2000, 1, 1, tzinfo=timezone.utc), until=far
    )
    assert denied.outcome == "refused" and "policy_denied" in denied.error_codes
    assert (
        collect_observations(
            stack.control.engine, "tenant-b", since=datetime(2000, 1, 1, tzinfo=timezone.utc), until=far
        )
        == ()
    )
    assert collect_observations(stack.control.engine, "tenant-a", since=far, until=far + timedelta(days=1)) == ()


def test_no_runtime_or_api_module_depends_on_the_drift_monitors():
    for path in [*(SERVICE / "app/runtime").glob("*.py"), SERVICE / "app/main.py", SERVICE / "app/api_v2.py"]:
        assert "app.drift" not in path.read_text(), path.name
    for path in (SERVICE / "app/drift").glob("*.py"):
        body = path.read_text()
        assert "INSERT" not in body.upper().replace("INSERTED", "") and "UPDATE " not in body.upper()


# ---- pinned corpus evaluation (thresholds are PROPOSED, not approved) ----


def test_the_drift_corpus_meets_its_proposed_thresholds_and_stays_unapproved(tmp_path):
    report = drift_eval.run_corpus(tmp_path)
    failed = [(c["case_id"], c["detail"]) for c in report["cases"] if not c["passed"]]
    assert not failed, failed
    unmet = {name: gate for name, gate in report["gates"].items() if not gate["meets"]}
    assert report["meets_thresholds"] and not unmet and len(report["cases"]) == 18, unmet
    assert report["approval"]["status"] == "proposed" and report["policy_status"] == "proposed"
    markdown = drift_eval.render_markdown(report)
    assert "PROPOSED and NOT APPROVED" in markdown and "chosen without production data" in markdown


def test_the_drift_evaluation_detects_a_wrong_expectation_and_a_changed_corpus(tmp_path, monkeypatch):
    suite, thresholds = drift_eval.load_suite()
    bad = json.loads(json.dumps(suite))
    next(c for c in bad["cases"] if c["id"] == "D10")["expect_alerts"] = []  # claim a 1.6x latency jump is quiet
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(bad))
    forged = tmp_path / "thresholds.json"
    forged.write_text(json.dumps({**thresholds, "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest()}))
    monkeypatch.setattr(drift_eval, "CORPUS", corpus)
    monkeypatch.setattr(drift_eval, "THRESHOLDS", forged)
    report = drift_eval.run_corpus(tmp_path / "run")
    assert not report["meets_thresholds"] and not report["gates"]["case_agreement"]["meets"]
    assert not report["gates"]["false_alerts"]["meets"]
    assert report["gates"]["drift_recall"]["meets"]  # the monitors still raised every alert they should
    forged.write_text(json.dumps(thresholds))
    with pytest.raises(drift_eval.DriftSuiteLockError):
        drift_eval.load_suite()
