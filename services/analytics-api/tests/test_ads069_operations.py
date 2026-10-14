"""ADS-069: operations dashboard, runbooks for every alert and gate, and seeded failures that can be diagnosed and replayed."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from reference_stack import operations_eval as ops
from reference_stack.stack import build_stack

from app.drift.alerts import REQUIRED_RUNBOOK_SECTIONS, RUNBOOK_DIR, runbook_problems
from app.operations import GATES, OPS_RUNBOOKS, build_dashboard, diagnose_run, gate_rows, runbook_problems_all
from app.operations.dashboard import REPORTS
from packages.platform_contracts.ops_dashboard import DashboardAlert, GateRow
from packages.platform_contracts.quotas import OpsAlert

SERVICE = Path(__file__).resolve().parent.parent
PURPOSE, QUESTION = "analytics", "Show monthly revenue"


def test_every_operator_runbook_exists_with_its_required_sections():
    assert runbook_problems_all() == []
    for runbook in OPS_RUNBOOKS:
        body = (RUNBOOK_DIR / f"{runbook}.md").read_text()
        assert all(section in body for section in REQUIRED_RUNBOOK_SECTIONS)
        assert "approval" in body.lower()  # every runbook says approvals are not the operator's to record


def test_a_missing_or_incomplete_runbook_is_reported(tmp_path):
    (tmp_path / "ops-a.md").write_text("# a\n\n## Symptom\n")
    problems = runbook_problems_all(["ops-a", "ops-b"], tmp_path)
    assert any("ops-b" in p and "missing" in p for p in problems)
    assert any("ops-a" in p and "Do not" in p for p in problems)


def test_every_alert_kind_and_gate_resolves_to_a_runbook():
    manager_source = (SERVICE / "app/quotas/manager.py").read_text()
    in_code = set(re.findall(r'"(ops-[a-z-]+)"', manager_source))
    assert in_code <= set(OPS_RUNBOOKS)
    assert {g.runbook_id for g in GATES} <= set(OPS_RUNBOOKS)
    assert {"ops-run-diagnosis", "ops-deployment-checklist", "ops-rolling-upgrade", "ops-failover"} <= set(OPS_RUNBOOKS)
    assert all(runbook_problems(r) == [] for r in {g.runbook_id for g in GATES})


def test_gates_echo_the_evidence_and_never_invent_an_approval():
    rows = {r.gate_id: r for r in gate_rows()}
    assert set(rows) == {g.gate_id for g in GATES}
    assert rows["golden"].status == "passing" and rows["golden"].approval_status == "approved"
    for gate in ("security", "poisoning", "drift", "resilience"):
        assert rows[gate].status == "unapproved" and rows[gate].approval_status == "proposed"
    assert all(r.status != "missing" for r in rows.values())
    missing = gate_rows(REPORTS / "nowhere")
    assert {r.status for r in missing} == {"missing"} and missing[0].approval_status is None


def test_a_failing_report_is_a_page_and_a_met_but_unapproved_report_is_not():
    weakened = {"approval": {"status": "approved"}, "meets_thresholds": False}
    fine = {"approval": {"status": "proposed"}, "meets_thresholds": True}
    rows = gate_rows(overrides={"security": weakened, "drift": fine})
    by_id = {r.gate_id: r for r in rows}
    assert by_id["security"].status == "failing" and by_id["drift"].status == "unapproved"
    board = build_dashboard("t", gates=rows)
    assert [(a.subject, a.runbook_id) for a in board.paging] == [("security", "ops-security-finding")]
    drills = {"restore": {"result": {"passed": False}}, "failover": {"result": {"passed": True}}}
    resilience = {r.gate_id: r for r in gate_rows(overrides={"resilience": drills})}["resilience"]
    assert resilience.status == "failing" and "restore" in resilience.detail


def test_open_security_findings_are_listed_by_id():
    report = json.loads((REPORTS / "ADS-067-security-report.json").read_text())
    board = build_dashboard("t", security_report=report)
    assert board.open_findings == tuple(sorted(f["id"] for f in report["findings"] if f["status"] != "resolved"))
    assert "F-03" in board.open_findings


def test_contracts_reject_unknown_fields_and_malformed_runbook_ids():
    with pytest.raises(ValidationError):
        DashboardAlert(source="quota", kind="k", severity="page", subject="s", runbook_id="not-a-runbook")
    with pytest.raises(ValidationError):
        GateRow(
            gate_id="g", packet="p", status="passing", approval_status=None, detail="d", runbook_id="ops-x", extra=1
        )
    alert = OpsAlert(
        kind="slo_latency", severity="warning", tenant_id="t", value=9, threshold=8, runbook_id="ops-slo-latency"
    )
    assert build_dashboard("t", slo_alerts=[alert]).alerts[0].runbook_id == "ops-slo-latency"


@pytest.mark.parametrize("name", list(ops.SCENARIOS))
def test_each_seeded_failure_is_diagnosed_and_replays_identically(name, tmp_path):
    first, second = ops.SCENARIOS[name](tmp_path / "a"), ops.SCENARIOS[name](tmp_path / "b")
    assert any(hit[0] == first["expected_kind"] and hit[1] == first["expected_runbook"] for hit in first["found"]), (
        first["found"]
    )
    assert ops._signature(first) == ops._signature(second)


def test_the_whole_drill_passes_and_names_a_runbook_for_each_scenario(tmp_path):
    report = ops.run_scenarios(tmp_path)
    assert report["ok"] and report["runbook_problems"] == []
    assert {r["expected_runbook"] for r in report["scenarios"].values()} <= set(OPS_RUNBOOKS)


def test_the_drill_fails_when_a_runbook_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "runbook_problems_all", lambda: ["ops-x: runbook file is missing"])
    assert ops.run_scenarios(tmp_path)["ok"] is False


def test_the_drill_fails_when_the_expected_alert_does_not_appear(tmp_path, monkeypatch):
    broken = dict(ops.SCENARIOS)
    broken["rate-limited"] = ops._quota_scenario(
        "rate_limited", "ops-rate-limit", lambda q, s, c: None
    )  # no traffic, no alert
    monkeypatch.setattr(ops, "SCENARIOS", broken)
    report = ops.run_scenarios(tmp_path)
    assert report["scenarios"]["rate-limited"]["diagnosed"] is False and report["ok"] is False


def test_the_drill_fails_when_the_wrong_runbook_is_attached(tmp_path, monkeypatch):
    broken = dict(ops.SCENARIOS)
    broken["slo-latency"] = ops._quota_scenario("slo_latency", "ops-rate-limit", ops._latency)
    monkeypatch.setattr(ops, "SCENARIOS", broken)
    assert ops.run_scenarios(tmp_path)["scenarios"]["slo-latency"]["diagnosed"] is False


def test_diagnosing_a_run_is_read_only_names_the_decision_and_carries_no_content(tmp_path):
    stack = build_stack("duckdb", tmp_path, denied=True)
    who = stack.verifier().verify(stack.token("requester"))
    response = stack.service().analyze(who, purpose=PURPOSE, idempotency_key="diag-key-000001", request_text=QUESTION)
    before = stack.control.replay_transitions(run_id=response.run_id, tenant_id=who.tenant_id, purpose=PURPOSE)
    diagnosis = diagnose_run(stack.control, tenant_id=who.tenant_id, run_id=response.run_id, purpose=PURPOSE)
    after = stack.control.replay_transitions(run_id=response.run_id, tenant_id=who.tenant_id, purpose=PURPOSE)
    assert before == after
    assert diagnosis.terminal_kind == "refused" and diagnosis.last_node == "policy" and diagnosis.history_contiguous
    assert diagnosis.path[0] == "bootstrap" and diagnosis.runbook_id == "ops-run-diagnosis"
    text = diagnosis.model_dump_json()
    assert response.run_id not in text and QUESTION not in text and "revenue" not in text.lower()
    assert (
        diagnosis.digest()
        == diagnose_run(stack.control, tenant_id=who.tenant_id, run_id=response.run_id, purpose=PURPOSE).digest()
    )


def test_a_gap_in_the_history_is_reported_not_hidden(tmp_path):
    from sqlalchemy import text

    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    response = stack.service().analyze(who, purpose=PURPOSE, idempotency_key="diag-key-000002", request_text=QUESTION)
    with (
        stack.control.engine.begin() as connection
    ):  # simulate damage directly in the database (the triggers guard the app path)
        try:
            connection.execute(text("DROP TRIGGER IF EXISTS analytics_run_transitions_no_delete"))
        except Exception:
            pass
        names = [r[0] for r in connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))]
        for name in names:
            if "transitions" in name:
                connection.execute(text(f"DROP TRIGGER {name}"))
        connection.execute(
            text("DELETE FROM analytics_run_transitions WHERE transition_seq=3 AND run_id=:r"), {"r": response.run_id}
        )
    diagnosis = diagnose_run(stack.control, tenant_id=who.tenant_id, run_id=response.run_id, purpose=PURPOSE)
    assert diagnosis.history_contiguous is False and diagnosis.path == ()


def test_the_dashboard_holds_counts_ids_and_codes_only(tmp_path):
    report = ops.run_scenarios(tmp_path)
    blob = json.dumps(report, default=str).lower()
    for forbidden in ("select ", "monthly revenue", "bearer", "password", "authorization", "request_text"):
        assert forbidden not in blob
    board = build_dashboard("t", gates=gate_rows())
    assert "sql" not in board.model_dump_json().lower()


def test_the_checked_in_report_is_current_and_passing():
    stored = json.loads((REPORTS / "ADS-069-operations-report.json").read_text())
    assert stored["ok"] is True and set(stored["scenarios"]) == set(ops.SCENARIOS)
    assert stored["runbooks_checked"] == list(OPS_RUNBOOKS)
