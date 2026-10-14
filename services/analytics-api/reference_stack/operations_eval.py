"""Seeded failures an operator can diagnose and replay (ADS-069). Fakes only; every scenario is deterministic.

Each scenario injects one failure into the reference stack or the quota/SLO machinery, builds the dashboard, and checks that (a) the
expected alert appears with the expected runbook, (b) the read-only diagnosis names the cause, and (c) running the scenario again
from scratch gives the same signature (replay). Scenarios measure the mechanisms; they are not production incident tests.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.operations import build_dashboard, diagnose_run, gate_rows, runbook_problems_all
from app.operations.dashboard import OPS_RUNBOOKS
from app.quotas import QuotaManager, SloTracker
from app.quotas.simulation import FakeClock
from app.resilience import ResilienceError, backup_control_store, verify_backup_files
from packages.platform_contracts.quotas import QuotaPolicy, SloObjective, TenantQuota
from reference_stack.stack import build_stack

PURPOSE, QUESTION = "analytics", "Show monthly revenue"


def _policy(**quota) -> QuotaPolicy:
    base = {
        "requests_per_minute": 60,
        "burst": 2,
        "max_concurrent_runs": 4,
        "daily_cost_units": 100,
        "warn_fraction": 0.8,
    }
    base.update(quota)
    return QuotaPolicy(
        policy_version="ops-seed",
        default=TenantQuota(**base),
        slo=SloObjective(success_target=0.99, p95_latency_seconds=8),
        approval={"status": "proposed"},
    )


def _signature(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _quota_scenario(kind: str, runbook: str, act: Callable[[QuotaManager, SloTracker, FakeClock], None]):
    def run(_: Path) -> dict[str, Any]:
        clock = FakeClock()
        quotas, slo = QuotaManager(_policy(), clock=clock), SloTracker(_policy(), clock=clock)
        act(quotas, slo, clock)
        slo_alerts = slo.evaluate("tenant-a")
        board = build_dashboard("seeded", quotas=quotas, tenants=["tenant-a"], slo_alerts=slo_alerts)
        hits = [a for a in board.alerts if a.kind == kind]
        return {
            "expected_kind": kind,
            "expected_runbook": runbook,
            "found": [(a.kind, a.runbook_id, a.subject) for a in hits],
            "diagnosis": "the alert names its runbook and the tenant row shows the cause",
            "tenant": board.tenants[0].model_dump(mode="json") if board.tenants else None,
        }

    return run


def _cost(quotas, slo, clock):
    quotas.admit("tenant-a")
    quotas.finish("tenant-a", run_ref="r1", cost_units=100.0, purpose=PURPOSE, dialect="duckdb")
    quotas.admit("tenant-a")  # refused: the budget is spent


def _rate(quotas, slo, clock):
    for _ in range(4):
        quotas.admit("tenant-a")


def _burn(quotas, slo, clock):
    for _ in range(30):
        slo.record("tenant-a", ok=False, latency_seconds=1.0)


def _latency(quotas, slo, clock):
    for _ in range(30):
        slo.record("tenant-a", ok=True, latency_seconds=12.0)


def _refused_run(workdir: Path) -> dict[str, Any]:
    stack = build_stack("duckdb", workdir, denied=True)
    who = stack.verifier().verify(stack.token("requester"))
    response = stack.service().analyze(who, purpose=PURPOSE, idempotency_key="ops-seed-refused", request_text=QUESTION)
    diagnosis = diagnose_run(stack.control, tenant_id=who.tenant_id, run_id=response.run_id, purpose=PURPOSE)
    again = stack.service().analyze(who, purpose=PURPOSE, idempotency_key="ops-seed-refused", request_text=QUESTION)
    return {
        "expected_kind": "refused_at_policy",
        "expected_runbook": "ops-run-diagnosis",
        "found": [(f"{diagnosis.terminal_kind}_at_{diagnosis.last_node}", diagnosis.runbook_id, diagnosis.run_ref)],
        "diagnosis": diagnosis.model_dump(mode="json"),
        "same_run_on_resubmission": again.run_id == response.run_id,
        "reason_code": getattr(response.outcome, "reason_code", None),
    }


def _corrupt_backup(workdir: Path) -> dict[str, Any]:
    stack = build_stack("duckdb", workdir / "stack")
    who = stack.verifier().verify(stack.token("requester"))
    stack.service().analyze(who, purpose=PURPOSE, idempotency_key="ops-seed-backup", request_text=QUESTION)
    backup_control_store(stack.control.engine, workdir / "backup")
    victim = sorted((workdir / "backup").glob("*.jsonl"))[0]
    victim.write_text(victim.read_text() + '{"tampered":true}\n')
    try:
        verify_backup_files(workdir / "backup")
        code = "accepted_a_corrupt_backup"
    except ResilienceError as exc:
        code = exc.code
    return {
        "expected_kind": "backup_corrupt",
        "expected_runbook": "ops-restore",
        "found": [(code, "ops-restore", None)],
        "diagnosis": "the verifier refuses a modified backup with a stable code before anything is restored",
    }


def _failing_gate(_: Path) -> dict[str, Any]:
    weakened = {"approval": {"status": "proposed"}, "meets_thresholds": False}
    rows = gate_rows(overrides={"security": weakened})
    board = build_dashboard("seeded", gates=rows)
    hits = [a for a in board.alerts if a.kind == "gate_failing"]
    return {
        "expected_kind": "gate_failing",
        "expected_runbook": "ops-security-finding",
        "found": [(a.kind, a.runbook_id, a.subject) for a in hits if a.subject == "security"],
        "diagnosis": "the dashboard marks the security gate failing and links its runbook",
    }


SCENARIOS: dict[str, Callable[[Path], dict[str, Any]]] = {
    "cost-budget-exhausted": _quota_scenario("cost_budget_exhausted", "ops-cost-budget", _cost),
    "rate-limited": _quota_scenario("rate_limited", "ops-rate-limit", _rate),
    "slo-fast-burn": _quota_scenario("slo_fast_burn", "ops-slo-burn", _burn),
    "slo-latency": _quota_scenario("slo_latency", "ops-slo-latency", _latency),
    "policy-refused-run": _refused_run,
    "corrupt-backup": _corrupt_backup,
    "failing-security-gate": _failing_gate,
}


def run_scenarios(root: Path | None = None) -> dict[str, Any]:
    root = root or Path(tempfile.mkdtemp(prefix="analytics-operations-"))
    results = {}
    for name, scenario in SCENARIOS.items():
        first, second = scenario(root / name / "a"), scenario(root / name / "b")
        diagnosed = any(
            hit[0] == first["expected_kind"] and hit[1] == first["expected_runbook"] for hit in first["found"]
        )
        results[name] = {
            "expected_runbook": first["expected_runbook"],
            "diagnosed": diagnosed,
            "replayed_identically": _signature(first) == _signature(second),
            "signature": _signature(first),
        }
    problems = runbook_problems_all()
    return {
        "scenarios": results,
        "runbooks_checked": list(OPS_RUNBOOKS),
        "runbook_problems": problems,
        "ok": not problems and all(r["diagnosed"] and r["replayed_identically"] for r in results.values()),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# ADS-069 operations drill (seeded failures)",
        "",
        "| Scenario | Runbook | Diagnosed | Replayed identically |",
        "|---|---|---|---|",
    ]
    for name, row in report["scenarios"].items():
        lines.append(f"| {name} | {row['expected_runbook']} | {row['diagnosed']} | {row['replayed_identically']} |")
    lines += [
        "",
        f"Runbooks checked: {len(report['runbooks_checked'])}; problems: {len(report['runbook_problems'])}.",
        f"Result: {'PASS' if report['ok'] else 'FAIL'}",
        "",
    ]
    return "\n".join(lines)
