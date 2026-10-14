"""The operations dashboard and run diagnosis (ADS-069): read-only views over the signals the earlier packets already produce.

It aggregates quota usage and alerts, SLO alerts, drift alerts, release-gate evidence, and open security findings, and every alert
names a runbook. It never acts, never changes a threshold or a pointer, and never records an approval: a gate row echoes the
approval status written in its evidence file.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.drift.alerts import RUNBOOK_DIR, runbook_problems
from app.observability.core import run_ref
from app.quotas.manager import QuotaManager
from app.runtime.control_store import ControlStore
from packages.platform_contracts.drift import DriftReport
from packages.platform_contracts.ops_dashboard import Dashboard, DashboardAlert, GateRow, RunDiagnosis, TenantRow
from packages.platform_contracts.quotas import OpsAlert

REPORTS = RUNBOOK_DIR.parent / "reports"

# Operator runbooks (the drift-* runbooks belong to ADS-058). Every alert kind and every gate below must resolve to one of these.
OPS_RUNBOOKS = (
    "ops-cost-budget",
    "ops-rate-limit",
    "ops-slo-burn",
    "ops-slo-latency",
    "ops-run-diagnosis",
    "ops-release-gate",
    "ops-security-finding",
    "ops-restore",
    "ops-failover",
    "ops-deployment-checklist",
    "ops-rolling-upgrade",
)


@dataclass(frozen=True)
class Gate:
    gate_id: str
    packet: str
    report: str  # the evidence file under reports/
    runbook_id: str


GATES = (
    Gate("golden", "ADS-049", "ADS-049-m4-golden-report.json", "ops-release-gate"),
    Gate("triage", "ADS-051", "ADS-051-triage-report.json", "ops-release-gate"),
    Gate("proposals", "ADS-052", "ADS-052-proposals-report.json", "ops-release-gate"),
    Gate("dbt-proposals", "ADS-053", "ADS-053-dbt-proposals-report.json", "ops-release-gate"),
    Gate("prompt-registry", "ADS-054", "ADS-054-prompt-registry-report.json", "ops-release-gate"),
    Gate("review", "ADS-055", "ADS-055-review-report.json", "ops-release-gate"),
    Gate("evaluation", "ADS-056", "ADS-056-evaluation-report.json", "ops-release-gate"),
    Gate("rollout", "ADS-057", "ADS-057-rollout-report.json", "ops-release-gate"),
    Gate("drift", "ADS-058", "ADS-058-drift-report.json", "ops-release-gate"),
    Gate("poisoning", "ADS-059", "ADS-059-poisoning-report.json", "ops-release-gate"),
    Gate("security", "ADS-067", "ADS-067-security-report.json", "ops-security-finding"),
    Gate("resilience", "ADS-068", "ADS-068-resilience-report.json", "ops-restore"),
)


def _gate_row(gate: Gate, report: Mapping[str, Any] | None) -> GateRow:
    def row(status, approval, detail):
        return GateRow(
            gate_id=gate.gate_id,
            packet=gate.packet,
            status=status,
            approval_status=approval,
            detail=detail,
            runbook_id=gate.runbook_id,
        )

    if report is None:
        return row("missing", None, "no evidence file: run the packet's make target")
    if gate.gate_id == "resilience":  # the drills carry their own pass flags rather than thresholds
        failed = [name for name, drill in report.items() if not drill["result"]["passed"]]
        if failed:
            return row("failing", "proposed", "drills failed: " + ", ".join(sorted(failed)))
        return row("unapproved", "proposed", "drills passed against proposed objectives")
    approval = (report.get("approval") or {}).get("status")
    meets = report.get("meets_thresholds")
    if meets is False:
        return row("failing", approval, "thresholds not met")
    if approval != "approved":
        return row("unapproved", approval, "thresholds met but not approved by a person")
    return row("passing", approval, "thresholds met and approved")


def gate_rows(
    reports: Path = REPORTS, *, overrides: Mapping[str, Mapping[str, Any]] | None = None
) -> tuple[GateRow, ...]:
    rows = []
    for gate in GATES:
        report = (overrides or {}).get(gate.gate_id)
        if report is None:
            path = reports / gate.report
            report = json.loads(path.read_text()) if path.is_file() else None
        rows.append(_gate_row(gate, report))
    return tuple(rows)


def _quota_alert(alert: OpsAlert, source: str) -> DashboardAlert:
    return DashboardAlert(
        source=source,  # type: ignore[arg-type]
        kind=alert.kind,
        severity=alert.severity,
        subject=alert.tenant_id,
        value=alert.value,
        threshold=alert.threshold,
        runbook_id=alert.runbook_id,
    )


def build_dashboard(
    label: str,
    *,
    quotas: QuotaManager | None = None,
    tenants: Iterable[str] = (),
    slo_alerts: Iterable[OpsAlert] = (),
    drift: DriftReport | None = None,
    gates: Iterable[GateRow] = (),
    security_report: Mapping[str, Any] | None = None,
) -> Dashboard:
    alerts: list[DashboardAlert] = []
    rows: list[TenantRow] = []
    if quotas is not None:
        alerts += [_quota_alert(a, "quota") for a in quotas.alerts]
        for tenant in sorted(set(tenants)):
            usage = quotas.usage(tenant)
            rows.append(
                TenantRow(
                    tenant_id=tenant,
                    in_flight=usage.in_flight,
                    admitted=usage.admitted,
                    rate_limited=usage.rate_limited,
                    day_cost_units=usage.day_cost_units,
                    cost_by_purpose=dict(usage.by_purpose),
                )
            )
    alerts += [_quota_alert(a, "slo") for a in slo_alerts]
    for alert in drift.alerts if drift else ():
        alerts.append(
            DashboardAlert(
                source="drift",
                kind=f"drift_{alert.monitor}",
                severity="page" if alert.severity == "critical" else "warning",
                subject=alert.monitor,
                runbook_id=alert.runbook_id,
            )
        )
    gate_list = tuple(gates)
    for gate in gate_list:
        if gate.status == "failing":
            alerts.append(
                DashboardAlert(
                    source="gate",
                    kind="gate_failing",
                    severity="page",
                    subject=gate.gate_id,
                    runbook_id=gate.runbook_id,
                )
            )
    open_findings = tuple(
        sorted(f["id"] for f in (security_report or {}).get("findings", []) if f.get("status") != "resolved")
    )
    return Dashboard(
        generated_for=label, tenants=tuple(rows), alerts=tuple(alerts), gates=gate_list, open_findings=open_findings
    )


def diagnose_run(control: ControlStore, *, tenant_id: str, run_id: str, purpose: str) -> RunDiagnosis:
    """Read the durable state and transition history of one run. Reads only; reports ids, nodes, and codes."""
    state = control.load_run_state(run_id=run_id, tenant_id=tenant_id, purpose=purpose)
    try:
        transitions = control.replay_transitions(run_id=run_id, tenant_id=tenant_id, purpose=purpose)
        contiguous = True
    except Exception:  # a gap or a read failure is itself the diagnosis
        transitions, contiguous = (), False
    path = tuple(t["to_node"] or "end" for t in transitions)
    outcome = state.terminal_outcome
    return RunDiagnosis(
        run_ref=run_ref(run_id),
        status=state.status,
        terminal_kind=outcome.kind if outcome else None,
        last_node=next((t["from_node"] for t in reversed(transitions) if t["to_node"] is None), None)
        or (path[-1] if path else None),
        path=path,
        history_contiguous=contiguous,
        evidence_ids=tuple(e.evidence_id.replace(run_id, run_ref(run_id)) for e in outcome.evidence) if outcome else (),
        runbook_id="ops-run-diagnosis",
    )


def runbook_problems_all(ids: Iterable[str] = OPS_RUNBOOKS, root: Path = RUNBOOK_DIR) -> list[str]:
    problems: list[str] = []
    for runbook_id in ids:
        problems += runbook_problems(runbook_id, root)
    return problems
