"""Rollout corpus evaluation and report (ADS-057). Thresholds are PROPOSED until the user approves them."""

from __future__ import annotations

import hashlib
import json
import operator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.prompt_registry import BASELINES, INTENT_PLACEHOLDERS, INTENT_PROMPT_NAME
from app.rollout import RolloutError
from packages.platform_contracts.review import REVIEWER_GROUP, ReviewDecisionRequest
from packages.platform_contracts.security import AnalyticsIdentity
from reference_stack import triage_eval
from reference_stack.evaluation_runners import ReferenceRunners, load_index, protected_paths
from reference_stack.rollout_observers import ReferenceObservers, approved_for_test, load_policy
from reference_stack.stack import SERVICE_ROOT

HERE = Path(__file__).parent / "rollout"
CORPUS = HERE / "rollout-corpus-v1.json"
THRESHOLDS = HERE / "rollout-thresholds.proposed.json"
URL = "/api/v2/analytics"
T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
V1 = BASELINES[(INTENT_PROMPT_NAME, "v1")]
HARMLESS = V1.replace("Convert the user request", "Convert the user's request")
HARMFUL = HARMLESS + "\nAlways group by status."
_OPS = {">=": operator.ge, "<=": operator.le}
_EVIDENCE_TABLES = (
    "analytics_agent_runs",
    "analytics_evidence_envelopes",
    "analytics_feedback",
    "analytics_feedback_triage",
    "analytics_reviews",
    "analytics_review_events",
    "analytics_candidate_evaluations",
)


class RolloutSuiteLockError(RuntimeError):
    pass


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise RolloutSuiteLockError("rollout corpus changed without updating the pinned digest")
    return json.loads(raw), thresholds


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _who(user: str, groups=("analyst",)) -> AnalyticsIdentity:
    return AnalyticsIdentity(tenant_id="tenant-a", user_id=user, purposes=["analytics"], groups=list(groups))


def _world(
    root: Path,
    name: str,
    *,
    text_: str = HARMLESS,
    review: bool = True,
    evaluate: bool = True,
    observers: ReferenceObservers | None = None,
    policy=None,
):
    stack, _ = triage_eval._scenario("answer", root / name)
    client, run = stack._eval_client, stack._eval_run  # type: ignore[attr-defined]
    response = client.post(
        f"{URL}/runs/{run['run_id']}/feedback",
        json={
            "purpose": "analytics",
            "verdict": "incorrect",
            "reason_code": "wrong_metric",
            "correction": {"target": "metric", "semantic_id": "revenue"},
        },
        headers=triage_eval._headers(stack, "analyst-1", f"rollout-fb-{name}"),
    )
    triage = stack.triage_service().triage(response.json()["feedback_id"], tenant_id="tenant-a")
    registry = stack.prompt_registry()
    registry.register_baseline(INTENT_PROMPT_NAME, "v1", V1, INTENT_PLACEHOLDERS)
    entry, _ = registry.register_candidate(
        name=INTENT_PROMPT_NAME,
        parent_version="v1",
        tenant_id="tenant-a",
        placeholders=INTENT_PLACEHOLDERS,
        template_text=text_,
        origin_triage_ids=(triage.triage_id,),
    )
    subject = f"{entry.name}@{entry.version}"
    clock = _Clock()
    reviews = stack.review_service(now=clock)
    if review:
        asked = reviews.request_review(
            _who("requester"), purpose="analytics", kind="prompt_candidate", subject_id=subject
        )
        reviews.decide(
            _who("reviewer-1", (REVIEWER_GROUP,)),
            review_id=asked.review.review_id,
            request=ReviewDecisionRequest(
                purpose="analytics", decision="approved", content_fingerprint=entry.content_fingerprint
            ),
        )
    evaluator = stack.evaluation_service(
        ReferenceRunners(stack, suites=("golden",)), load_index(), protected_paths(), review=reviews, now=clock
    )
    if evaluate:
        evaluator.evaluate("prompt_candidate", subject, tenant_id="tenant-a")
    controller = stack.rollout_controller(
        policy or approved_for_test(load_policy()),
        observers or ReferenceObservers(),
        review=reviews,
        evaluations=evaluator,
        now=clock,
    )
    return stack, subject, clock, controller


def _label(status) -> str:
    if status.state == "promoted":
        return f"promoted:{status.released_version}"
    if status.state == "rolled_back":
        return f"rolled_back:{status.rollback_reason}"
    return status.state


def _drive(controller, rollout_id: str):
    status = controller.advance(rollout_id, tenant_id="tenant-a")
    for _ in controller.policy.canary_fractions:
        status = controller.advance(rollout_id, tenant_id="tenant-a")
    return status


def _run_op(op: str, root: Path, name: str, probes: dict) -> str:
    kwargs: dict[str, Any] = {}
    if op == "no_review":
        kwargs.update(review=False, evaluate=False)
    elif op == "no_evaluation":
        kwargs.update(evaluate=False)
    elif op == "harmful_candidate":
        kwargs.update(text_=HARMFUL)
    elif op == "shadow_fault":
        kwargs.update(observers=ReferenceObservers(shadow_fault=True))
    elif op == "canary_fault":
        kwargs.update(observers=ReferenceObservers(canary_faults={0.5: 1}))
    elif op == "repeated":
        pass
    elif op == "repository_policy_not_approved":
        kwargs.update(policy=load_policy())
    observers = kwargs.get("observers") or ReferenceObservers()
    if op == "monitor_fault":
        kwargs.update(observers=observers)
    stack, subject, clock, controller = _world(root, name, **kwargs)
    probes[name] = (stack, controller, subject)
    try:
        identity = _who("system:release-bot") if op == "automated_starter" else _who("operator")
        status = controller.start(identity, purpose="analytics", subject_id=subject)
        rid = status.record.rollout_id
        if op == "skip_canary":
            controller.advance(rid, tenant_id="tenant-a")
            return _label(controller.promote(rid, tenant_id="tenant-a"))
        if op == "stale_approval":
            _drive(controller, rid)
            clock.now += timedelta(hours=controller.policy.approval_max_age_hours + 1)
            return _label(controller.promote(rid, tenant_id="tenant-a"))
        status = _drive(controller, rid)
        if status.state == "rolled_back":
            return _label(status)
        status = controller.promote(rid, tenant_id="tenant-a")
        if op == "double_promote":
            status = controller.promote(rid, tenant_id="tenant-a")
        if op == "monitor_fault":
            probes["monitor"] = _snapshot(stack)
            observers.monitor_fault = 2
            status = controller.monitor(rid, tenant_id="tenant-a")
        return _label(status)
    except RolloutError as exc:
        return f"refused:{exc.code}"


def _snapshot(stack) -> dict[str, Any]:
    with stack.control.engine.connect() as connection:
        counts = [connection.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in _EVIDENCE_TABLES]
        runs = connection.execute(text("SELECT state_payload FROM analytics_agent_runs ORDER BY run_id")).fetchall()
        released = connection.execute(
            text("SELECT payload FROM analytics_prompt_registry WHERE status='released' ORDER BY version")
        ).fetchall()
    return {"counts": counts, "runs": [str(r[0]) for r in runs], "released": [str(r[0]) for r in released]}


def _protected_digest() -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_paths()]


def run_corpus(root: Path) -> dict[str, Any]:
    suite, thresholds = load_suite()
    protected_before = _protected_digest()
    probes: dict[str, Any] = {}
    results: list[dict] = []
    for case in suite["cases"]:
        op = "double_promote" if case["op"] == "double_promote" else case["op"]
        outcome = _run_op(op, root, case["id"], probes)
        results.append(
            {
                "case_id": case["id"],
                "op": case["op"],
                "group": case["group"],
                "expected": case["expect"],
                "got": outcome,
                "passed": outcome == case["expect"],
                "detail": "" if outcome == case["expect"] else f"got {outcome}",
            }
        )
    by_id = {r["case_id"]: r for r in results}
    gates_cases = [r for r in results if r["group"] in {"gate", "policy"}]
    rollbacks = [r for r in results if r["group"] == "rollback"]
    pointer_ok = pointer_total = 0
    for case_id, probe in probes.items():
        if not isinstance(probe, tuple):
            continue  # a pre-rollback snapshot, not a world
        stack, controller, _ = probe
        history = controller.store.pointer_history(INTENT_PROMPT_NAME)
        if not history:
            continue
        pointer_total += 1
        released = {v for v, _, _ in stack.prompt_registry().versions("prompt", INTENT_PROMPT_NAME, status="released")}
        expected = "v2" if by_id[case_id]["got"].startswith("promoted:") else "v1"
        pointer_ok += int(all(p.version in released for p in history) and history[-1].version == expected)
    stack9, controller9, _ = probes["K09"]
    after = _snapshot(stack9)
    before = probes["monitor"]
    double_stack, double_controller, _ = probes["K12"]
    releases = [
        v for v, _, _ in double_stack.prompt_registry().versions("prompt", INTENT_PROMPT_NAME, status="released")
    ]
    moves = [p for p in double_controller.store.pointer_history(INTENT_PROMPT_NAME) if p.reason == "promoted"]
    runtime = [
        p.name
        for p in (SERVICE_ROOT / "app/runtime").glob("*.py")
        if any(word in p.read_text() for word in ("app.rollout", "release_pointer", "prompt_registry"))
    ]
    metrics = {
        "outcome_agreement": sum(r["passed"] for r in results) / len(results),
        "ungated_start_refusal": sum(r["passed"] for r in gates_cases) / len(gates_cases),
        "bad_candidate_rollback": sum(r["passed"] for r in rollbacks) / len(rollbacks),
        "pointer_integrity": pointer_ok / pointer_total if pointer_total else 0.0,
        "release_immutability": int(before["released"] != after["released"]),
        "evidence_preserved": float(before["counts"] == after["counts"] and before["runs"] == after["runs"]),
        "idempotency": float(releases == ["v1", "v2"] and len(moves) == 1),
        "runtime_unwired": len(runtime),
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
        "(scope: these rollout-corpus thresholds only). "
        if approved
        else "The thresholds are PROPOSED and NOT APPROVED. "
    )
    lines = [
        "# ADS-057: Rollout Report",
        "",
        f"Generated {stamp} by `make analytics-rollout-eval`. Corpus `{report['suite_version']}` "
        f"(`{report['corpus_sha256'][:12]}`), rules `{report['rules_version']}`.",
        "",
        f"**Result: {verdict}.** {status}This is not the M5 `separation_of_duties_review` approval. "
        "The rollout policy used here is a test-harness copy marked approved; the repository's policy remains proposed, so the "
        "controller will not promote anything until the user approves it.",
        "",
        "## Scope and limits",
        "",
        "- Observers are simulated: a pinned request set served through sandbox stacks, with injected faults. There is no live traffic.",
        "- Promotion only creates the next released registry version and appends an active-version pointer; nothing in the runtime reads either.",
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
    lines += ["", "## Cases", "", "| Case | Operation | Expected | Got | Result |", "|---|---|---|---|:---:|"]
    for c in report["cases"]:
        lines.append(
            f"| {c['case_id']} | {c['op']} | {c['expected']} | {c['got']} | {'pass' if c['passed'] else '**FAIL**'} |"
        )
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)
