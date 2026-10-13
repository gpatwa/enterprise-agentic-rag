"""Drift corpus evaluation and report (ADS-058). Thresholds and alert rules are PROPOSED until the user approves them."""

from __future__ import annotations

import hashlib
import json
import operator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.drift import (
    InMemoryAlertSink,
    collect_observations,
    deliver,
    evaluate_drift,
    runbook_problems,
)
from packages.platform_contracts.drift import DriftPolicy, RunObservation
from reference_stack import triage_eval
from reference_stack.evaluation_runners import protected_paths
from reference_stack.stack import SERVICE_ROOT

HERE = Path(__file__).parent / "drift"
CORPUS = HERE / "drift-corpus-v1.json"
THRESHOLDS = HERE / "drift-thresholds.proposed.json"
POLICY = HERE / "drift-policy.proposed.json"
T0 = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
_OPS = {">=": operator.ge, "<=": operator.le}
_CONTROL_TABLES = (
    "analytics_agent_runs",
    "analytics_evidence_envelopes",
    "analytics_feedback",
    "analytics_run_transitions",
)
# Classes are assigned to runs in this order; the remainder succeeds.
_CLASSES = (
    ("stale", "review_required", "stale_context"),
    ("malformed", "failed", "malformed_model_output"),
    ("clarify", "clarification_required", None),
    ("failed", "failed", "execution_failed"),
    ("refused", "refused", "policy_denied"),
)


class DriftSuiteLockError(RuntimeError):
    pass


def load_policy(path: Path = POLICY) -> DriftPolicy:
    return DriftPolicy.model_validate_json(path.read_text())


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise DriftSuiteLockError("drift corpus changed without updating the pinned digest")
    return json.loads(raw), thresholds


def make_window(
    spec: dict[str, Any], *, start: datetime = T0, tenant_id: str = "tenant-a"
) -> tuple[RunObservation, ...]:
    """A deterministic synthetic window: exact class counts, fixed latency and cost patterns, no randomness."""
    n = int(spec["n"])
    assignments: list[tuple[str, str | None]] = []
    for key, outcome, code in _CLASSES:
        assignments += [(outcome, code)] * round(n * spec.get(key, 0.0))
    assignments += [("succeeded", None)] * (n - len(assignments))
    empty = round(n * spec.get("empty_retrieval", 0.0))
    window = []
    for index, (outcome, code) in enumerate(assignments):
        window.append(
            RunObservation(
                run_id=f"syn-{start:%Y%m%d}-{index}",
                tenant_id=tenant_id,
                observed_at=start + timedelta(minutes=index),
                outcome=outcome,
                error_codes=(code,) if code else (),
                context_items=0 if index < empty else int(spec["items"]),
                context_age_hours=float(spec["max_age_hours"]) if index == 0 else 1.0,
                latency_ms=spec["latency_ms"] * (0.8 + 0.4 * ((index * 7) % 10) / 9),
                cost_units=spec["cost"] * (0.9 + 0.2 * ((index * 3) % 10) / 9),
            )
        )
    return tuple(window)


def _protected_digest() -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_paths()]


def _counts(stack) -> list[int]:
    with stack.control.engine.connect() as connection:
        return [connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() for table in _CONTROL_TABLES]


def run_corpus(root: Path) -> dict[str, Any]:
    suite, thresholds = load_suite()
    policy = load_policy()
    protected_before = _protected_digest()
    results: list[dict] = []
    raised: list[tuple[str, str]] = []  # (case id, rule id)
    runbook_failures: list[str] = []
    for case in suite["cases"]:
        report = evaluate_drift(
            make_window(case["baseline"]), make_window(case["current"], start=T0 + timedelta(days=1)), policy
        )
        got = sorted(alert.rule_id for alert in report.alerts)
        expected = sorted(case["expect_alerts"])
        skip_ok = True
        if "expect_skipped" in case:
            wanted = case["expect_skipped"]
            matching = [s for s in report.skipped if s.reason == wanted["reason"]]
            skip_ok = len(matching) == wanted["count"]
        raised += [(case["id"], rule) for rule in got]
        for alert in report.alerts:
            runbook_failures += runbook_problems(alert.runbook_id)
        results.append(
            {
                "case_id": case["id"],
                "name": case["name"],
                "group": case["group"],
                "expected": ",".join(expected) or "none",
                "got": ",".join(got) or "none",
                "skipped": f"{len(report.skipped)}",
                "passed": got == expected and skip_ok,
                "detail": "" if got == expected and skip_ok else f"got {got}, skipped {len(report.skipped)}",
            }
        )
    drift_cases = [c for c in suite["cases"] if c["expect_alerts"]]
    quiet_cases = [c["id"] for c in suite["cases"] if not c["expect_alerts"]]
    expected_pairs = {(c["id"], r) for c in drift_cases for r in c["expect_alerts"]}
    silence_cases = [c["id"] for c in suite["cases"] if c["group"] == "silence"]
    rule_runbooks = [p for rule in policy.rules for p in runbook_problems(rule.runbook_id)]

    # A real run on the reference stack: extraction works and the monitors write nothing.
    stack, _ = triage_eval._scenario("answer", root / "real")
    before = _counts(stack)
    observed = collect_observations(
        stack.control.engine,
        "tenant-a",
        since=datetime(2000, 1, 1, tzinfo=timezone.utc),
        until=datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    sink = InMemoryAlertSink()
    deliver(evaluate_drift(observed, observed, policy), sink)
    extraction_ok = (
        len(observed) == 1
        and observed[0].outcome == "succeeded"
        and observed[0].latency_ms is not None
        and observed[0].cost_units is not None
        and observed[0].context_items is not None
        and not observed[0].error_codes
    )
    runtime = [p.name for p in (SERVICE_ROOT / "app/runtime").glob("*.py") if "app.drift" in p.read_text()]
    main_text = (SERVICE_ROOT / "app/main.py").read_text() + (SERVICE_ROOT / "app/api_v2.py").read_text()
    metrics = {
        "case_agreement": sum(r["passed"] for r in results) / len(results),
        "drift_recall": len(expected_pairs & set(raised)) / len(expected_pairs),
        "false_alerts": len(set(raised) - expected_pairs),
        "runbook_coverage": float(not runbook_failures and not rule_runbooks),
        "insufficient_data_silence": sum(
            r["passed"] and r["got"] == "none" for r in results if r["case_id"] in silence_cases
        )
        / len(silence_cases),
        "quiet_window_silence": sum(r["got"] == "none" for r in results if r["case_id"] in quiet_cases)
        / len(quiet_cases),
        "real_run_extraction": float(extraction_ok),
        "monitor_writes": sum(a != b for a, b in zip(before, _counts(stack), strict=True)),
        "runtime_unwired": len(runtime) + int("app.drift" in main_text),
        "protected_file_writes": sum(a != b for a, b in zip(protected_before, _protected_digest(), strict=True)),
    }
    gates = {
        name: {
            "value": metrics[name],
            "op": g["op"],
            "threshold": g["value"],
            "meets": bool(_OPS[g["op"]](metrics[name], g["value"])),
            "measure": g["measure"],
        }
        for name, g in thresholds["gates"].items()
    }
    return {
        "suite_version": suite["suite_version"],
        "rules_version": thresholds["rules_version"],
        "corpus_sha256": thresholds["corpus_sha256"],
        "approval": thresholds["approval"],
        "policy_version": policy.policy_version,
        "policy_status": policy.approval.status,
        "meets_thresholds": all(g["meets"] for g in gates.values()),
        "gates": gates,
        "not_measured": thresholds["not_measured"],
        "cases": results,
    }


def render_markdown(report: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    approval = report["approval"]
    approved = approval["status"] == "approved"
    label = "approved" if approved else "proposed"
    verdict = f"MEETS the {label} thresholds" if report["meets_thresholds"] else f"DOES NOT MEET the {label} thresholds"
    status = (
        f"The thresholds were approved by {approval['approved_by']} on {approval['approved_at']} "
        "(scope: these drift-corpus thresholds only). "
        if approved
        else "The thresholds are PROPOSED and NOT APPROVED. "
    )
    lines = [
        "# ADS-058: Drift Monitor Report",
        "",
        f"Generated {stamp} by `make analytics-drift-eval`. Corpus `{report['suite_version']}` "
        f"(`{report['corpus_sha256'][:12]}`), rules `{report['rules_version']}`, alert policy "
        f"`{report['policy_version']}` (**{report['policy_status']}**).",
        "",
        f"**Result: {verdict}.** {status}This is not the M5 `separation_of_duties_review` approval. "
        "The alert thresholds in the drift policy are also proposed: they were chosen without production data.",
        "",
        "## Scope and limits",
        "",
        "- Windows are synthetic and deterministic; the one real run only proves extraction works. There is no production traffic.",
        "- Monitors are advisory and read-only. An alert starts no rollback and changes no run, release, pointer, or threshold.",
        "",
        f"## Metrics against {label} thresholds",
        "",
        "| Metric | Measured | Gate | Meets |",
        "|---|---:|---:|:---:|",
    ]
    for name, g in report["gates"].items():
        lines.append(
            f"| `{name}` | {g['value']:.4g} | {g['op']} {g['threshold']} | {'yes' if g['meets'] else '**NO**'} |"
        )
    lines += [
        "",
        "## Cases",
        "",
        "| Case | Name | Expected alerts | Got | Skipped rules | Result |",
        "|---|---|---|---|---:|:---:|",
    ]
    for c in report["cases"]:
        lines.append(
            f"| {c['case_id']} | {c['name']} | {c['expected']} | {c['got']} | {c['skipped']} | {'pass' if c['passed'] else '**FAIL**'} |"
        )
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)
