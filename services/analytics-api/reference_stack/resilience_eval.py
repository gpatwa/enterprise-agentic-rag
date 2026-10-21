"""Resilience drills and pinned checkpoint fixtures (ADS-068). Objectives are PROPOSED until the user approves them.

The drills run on the reference stack with fakes: a logical backup and verified restore into a fresh database (measuring recovery
time and data loss against the recovery objectives) and a worker crash with lease takeover and a zombie worker (fencing). They
measure the mechanisms; real RPO and RTO need the production database and its backup tooling.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.resilience import backup_control_store, restore_control_store
from app.runtime import AgentGraphRunner, BootstrapRequest, ControlStore, governed_graph_v2
from app.runtime.analyze_service import ServiceError, request_id_for
from app.runtime.control_store import LeaseUnavailable, StaleWorkerError
from packages.platform_contracts.feedback import FeedbackSubmission
from packages.platform_contracts.operations import DrillResult
from packages.platform_contracts.resilience import ResilienceObjectives
from reference_stack.stack import SERVICE_ROOT, build_stack

OBJECTIVES = SERVICE_ROOT / "resilience" / "objectives.proposed.json"
FIXTURES = SERVICE_ROOT / "tests" / "fixtures" / "checkpoints"
FIXTURE_LOCK = FIXTURES / "checkpoints.lock.json"
PURPOSE = "analytics"
QUESTION = "Show monthly revenue"


def load_objectives(path: Path = OBJECTIVES) -> ResilienceObjectives:
    return ResilienceObjectives.model_validate_json(path.read_text())


class _Clock:
    """A settable clock. It starts at the real current time: runs carry real-time deadlines, so a fixed date would expire them."""

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class RecordingControlStore(ControlStore):
    def __init__(self, engine, **kwargs) -> None:
        super().__init__(engine, **kwargs)
        self.leases: list[Any] = []

    def acquire_lease(self, **kwargs):
        lease = super().acquire_lease(**kwargs)
        self.leases.append(lease)
        return lease


def _who(stack, user="requester"):
    return stack.verifier().verify(stack.token(user))


def _analyze(service, who, key):
    return service.analyze(who, purpose=PURPOSE, idempotency_key=key, request_text=QUESTION)


def _run_states(stack) -> dict[str, str]:
    with stack.control.engine.connect() as connection:
        rows = connection.execute(text("SELECT run_id, state_payload FROM analytics_agent_runs ORDER BY run_id")).all()
    return {
        run_id: json.dumps(json.loads(payload) if isinstance(payload, str) else payload, sort_keys=True)
        for run_id, payload in rows
    }


def drill_restore(
    root: Path, objectives: ResilienceObjectives, *, crash_after_seconds: float = 600.0
) -> dict[str, Any]:
    """Back up, keep writing, lose the database, restore into a fresh one, and check what survived."""
    stack = build_stack(
        "duckdb", root / "primary", review_threshold=1e-9
    )  # every run pauses for review, then some are decided
    service, who, reviewer = stack.service(), _who(stack), _who(stack, "reviewer")
    paused = [_analyze(service, who, f"restore-key-{i:04d}") for i in range(5)]
    for run in paused[:2]:
        review = stack.control.get_review(run.outcome.review_id, tenant_id="tenant-a", purpose=PURPOSE)
        service.decide_review(
            reviewer,
            purpose=PURPOSE,
            run_id=run.run_id,
            decision="approved",
            plan_fingerprint=review.plan_fingerprint,
            note=None,
        )
    feedback = stack.feedback_service().submit(
        who,
        run_id=paused[0].run_id,
        idempotency_key="restore-feedback-1",
        submission=FeedbackSubmission(purpose=PURPOSE, verdict="incorrect", reason_code="wrong_metric"),
    )
    before_backup = _run_states(stack)
    started = time.perf_counter()
    manifest = backup_control_store(stack.control.engine, root / "backup", clock=_Clock())
    backup_seconds = time.perf_counter() - started
    for index in range(3):  # written after the backup: this is what a crash now would lose
        _analyze(service, who, f"restore-after-{index:04d}")
    after_backup = _run_states(stack)

    replacement = build_stack("duckdb", root / "replacement", review_threshold=1e-9)  # a new, empty, migrated database
    started = time.perf_counter()
    restored = restore_control_store(root / "backup", replacement.control.engine)
    rto = time.perf_counter() - started
    survivors = _run_states(replacement)
    findings: list[str] = []
    if crash_after_seconds > objectives.rpo_seconds:
        findings.append("rpo_exceeded")
    if rto > objectives.rto_seconds:
        findings.append("rto_exceeded")
    if survivors != before_backup:
        findings.append("restored_runs_differ_from_backup_point")
    # What a restore does not bring back: answers' rows and explanations live in process-local stores.
    try:
        outcome = replacement.service().status(who, purpose=PURPOSE, run_id=paused[0].run_id).outcome
        rows_survive = outcome is not None and outcome.outcome == "answer"
    except ServiceError:
        rows_survive = False
    return {
        "result": DrillResult(drill="restore", passed=not findings, duration_seconds=rto, findings=findings),
        "measured": {
            "backup_seconds": backup_seconds,
            "restore_seconds": rto,
            "data_loss_window_seconds": crash_after_seconds,
            "runs_in_backup": len(before_backup),
            "runs_lost": len(after_backup) - len(survivors),
            "rows_backed_up": manifest.object_count,
            "evidence_envelopes_verified": restored["evidence_envelopes"],
            "feedback_restored": bool(feedback),
            "answer_rows_survive_restart": rows_survive,
        },
    }


def drill_failover(root: Path, objectives: ResilienceObjectives) -> dict[str, Any]:
    """Worker A crashes mid-run; B cannot take over until the lease expires, then finishes it; zombie A is fenced off."""
    stack = build_stack("duckdb", root / "failover")
    store = RecordingControlStore(stack.control.engine, lease_seconds=int(objectives.lease_seconds))
    stack.control = store
    who = _who(stack)
    request = BootstrapRequest(
        request_id=request_id_for(who, "failover-request-1"), request_text=QUESTION, identity=who
    )
    state = stack.new_state(request, "failover-run-0001", PURPOSE)
    crashed = {"done": False}

    def handlers():
        nodes = stack.nodes(who, request)
        original = nodes["explain"]

        def explain(node_input):
            if not crashed["done"]:
                crashed["done"] = True
                raise SystemExit("simulated worker crash after the execute checkpoint")
            return original(node_input)

        nodes["explain"] = explain
        return nodes

    clock_a = _Clock()
    t0 = clock_a.now
    clock_b = _Clock(t0)
    runner_a = AgentGraphRunner(store, governed_graph_v2(handlers()), now=clock_a)
    try:
        runner_a.start(state, owner_id="worker-a", lease_token="lease-a")
    except SystemExit:
        pass
    old_lease = store.leases[-1]
    at_crash = store.load_latest_checkpoint(run_id=state.run_id, tenant_id=state.tenant_id, purpose=PURPOSE)
    runner_b = AgentGraphRunner(store, governed_graph_v2(handlers()), now=clock_b)
    findings: list[str] = []
    clock_b.now = t0 + timedelta(seconds=objectives.lease_seconds / 2)
    try:
        runner_b.resume(
            run_id=state.run_id,
            tenant_id=state.tenant_id,
            purpose=PURPOSE,
            owner_id="worker-b",
            lease_token="lease-b-0",
        )
        findings.append("took_over_a_live_lease")
    except LeaseUnavailable:
        pass
    takeover_seconds = objectives.lease_seconds + 1
    clock_b.now = t0 + timedelta(seconds=takeover_seconds)
    result = runner_b.resume(
        run_id=state.run_id, tenant_id=state.tenant_id, purpose=PURPOSE, owner_id="worker-b", lease_token="lease-b-1"
    )
    if result.state.status != "terminal" or result.state.terminal_outcome.kind != "succeeded":
        findings.append("takeover_did_not_finish_the_run")
    try:  # the paused worker wakes up and tries to carry on under its old lease
        runner_a._execute(at_crash, old_lease)
        findings.append("zombie_worker_was_not_fenced")
    except (StaleWorkerError, LeaseUnavailable):
        pass
    executions = len(stack.executed_sql)
    if executions != 1:
        findings.append("the_query_ran_more_than_once")
    if takeover_seconds > objectives.lease_seconds * objectives.takeover_factor:
        findings.append("takeover_too_slow")
    transitions = store.replay_transitions(run_id=state.run_id, tenant_id=state.tenant_id, purpose=PURPOSE)
    if [t["transition_seq"] for t in transitions] != list(range(1, len(transitions) + 1)):
        findings.append("transition_history_not_contiguous")
    return {
        "result": DrillResult(
            drill="failover", passed=not findings, duration_seconds=float(takeover_seconds), findings=findings
        ),
        "measured": {
            "takeover_seconds": takeover_seconds,
            "lease_seconds": objectives.lease_seconds,
            "query_executions": executions,
            "fencing_seq_after_takeover": store.leases[-1].fencing_seq,
            "transitions": len(transitions),
        },
    }


def write_checkpoint_fixtures(directory: Path = FIXTURES) -> dict[str, str]:
    """Persist real run states as pinned fixtures; they are the compatibility contract for the next release."""
    import tempfile

    directory.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="analytics-fixtures-"))
    cases = {
        "waiting_review": dict(stack={"review_threshold": 1e-9}),
        "waiting_clarification": dict(stack={"ambiguous": True}),
        "terminal_succeeded": dict(stack={}),
        "terminal_refused": dict(stack={"denied": True}),
    }
    digests: dict[str, str] = {}
    for name, spec in cases.items():
        stack = build_stack("duckdb", root / name, **spec["stack"])
        who = _who(stack)
        run = _analyze(stack.service(), who, f"fixture-key-{name[:12]:<12}".replace(" ", "x"))
        state = stack.control.load_latest_checkpoint(run_id=run.run_id, tenant_id="tenant-a", purpose=PURPOSE)
        payload = state.model_dump(mode="json")
        text_ = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        (directory / f"{name}.json").write_text(text_)
        digests[name] = hashlib.sha256(text_.encode()).hexdigest()
    FIXTURE_LOCK.write_text(json.dumps({"release": "m6-wave-6c", "sha256": digests}, indent=2) + "\n")
    return digests


def render_markdown(
    drills: dict[str, dict[str, Any]], objectives: ResilienceObjectives, *, generated_at: datetime | None = None
) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    approved = objectives.approval.status == "approved"
    lines = [
        "# ADS-068: Resilience Drill Report",
        "",
        f"Generated {stamp} by `make analytics-resilience-drill`. Objectives `{objectives.objectives_version}` "
        f"(**{objectives.approval.status}**): RPO {objectives.rpo_seconds:g}s, RTO {objectives.rto_seconds:g}s, lease {objectives.lease_seconds:g}s.",
        "",
        "The objectives are "
        + ("approved by the user." if approved else "**PROPOSED and NOT APPROVED**.")
        + " This is not the M6 `security_and_operations_review`. The drills run on the reference stack with SQLite, DuckDB, and fakes: "
        "they measure the mechanisms, not production recovery.",
        "",
        "Restore seconds are wall-clock time on this machine; failover seconds are **simulated** (a fake clock advanced past the lease expiry), not elapsed time.",
        "",
        "| Drill | Passed | Seconds | Findings |",
        "|---|:---:|---:|---|",
    ]
    for name, drill in drills.items():
        result = drill["result"]
        lines.append(
            f"| {name} | {'yes' if result.passed else '**NO**'} | {result.duration_seconds:.3f} | {', '.join(result.findings) or '-'} |"
        )
    lines += ["", "## Measurements", ""]
    for name, drill in drills.items():
        lines.append(f"**{name}**")
        lines += [
            f"- `{key}`: {value:.4g}" if isinstance(value, float) else f"- `{key}`: {value}"
            for key, value in drill["measured"].items()
        ]
        lines.append("")
    lines += [
        "## What a restore does not bring back",
        "",
        "- Answer rows and explanations live in process-local stores, so a restored or restarted API cannot re-serve an old answer's rows: "
        "the evidence and fingerprints survive, the user re-asks. Compiled plans and policy values are also process-local, so a run "
        "paused for review before a restart fails closed on resume instead of executing.",
        "- Run leases are not restored; workers take new ones.",
        "",
    ]
    return "\n".join(lines)
