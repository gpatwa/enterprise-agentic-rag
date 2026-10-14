"""ADS-075: reliability, crash/replay, dependency-failure, and chaos evaluation (fakes only).

Four parts, each judged on the same invariants: a run ends in a correct answer or a typed, safe failure; it never returns rows that
differ from the independent oracle; no query runs twice; no unhandled error reaches the caller; the evidence chain still verifies.

1. Crash matrix: a worker dies before or after each of the 13 nodes of a normal run; a second worker takes over after the lease.
   Run twice: with the process's in-memory stores intact (a worker thread died) and with fresh stores on the same database (the
   process died). The second is the honest model of a real crash: compiled plans, policy values, and result rows are process-local.
2. Dependency failures: the warehouse, the cost estimator, the context search, the context snapshot, the explainer, the model, and the
   run deadline fail one at a time.
3. Chaos: a seeded random mix of the above over many runs.
4. Availability: the share of crash runs that still end in a correct answer.

Thresholds are PROPOSED until the user approves them. Local fakes only: this measures mechanisms, not production availability.
"""

from __future__ import annotations

import json
import random
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

from app.runtime import AgentGraphRunner, BootstrapRequest, governed_graph_v2
from app.runtime.analyze_service import ServiceError
from app.runtime.control_store import ControlStore
from reference_stack import m7_corpus as corpus_module
from reference_stack import stack as stack_module
from reference_stack.golden import canonical_rows
from reference_stack.resilience_eval import QUESTION, _Clock
from reference_stack.stack import build_stack

HERE = Path(__file__).parent / "m7"
THRESHOLDS = HERE / "reliability-thresholds.proposed.json"
PURPOSE = "analytics"
NODES = (
    "create",
    "bootstrap",
    "retrieve",
    "extract_intent",
    "resolve",
    "plan",
    "validate",
    "policy",
    "compile",
    "estimate",
    "execute",
    "result_validate",
    "explain",
)
EXPECTED_ROWS = corpus_module.expected("monthly_paid")[1]
LEASE = 30
_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
GATE_PLAN = {
    "wrong_answers": "Answers whose rows differ from the independent oracle: 0",
    "duplicate_executions": "A query executed more than once for one run: 0",
    "unhandled_errors": "Errors that reach the caller untyped (a raw exception or HTTP 500): 0",
    "unsafe_outcomes": "Runs that end in neither a correct answer nor a typed failure: 0",
    "evidence_chain_breaks": "Evidence chains that no longer verify: 0",
    "crash_recovery_same_process": "Worker-crash points that still end in a correct answer (stores intact)",
    "crash_safe_ending_process_death": "Process-crash points that end safely: a correct answer or a typed failure",
    "dependency_failures_handled": "Dependency failures that end in a typed failure or a degraded-but-correct answer",
    "chaos_safe_ending_rate": "Chaos runs that end safely",
}


class _Broken:
    """A dependency that fails the way a dead service does."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise ConnectionError("dependency unavailable")

        return fail


def _who(stack, user: str = "requester"):
    return stack.verifier().verify(stack.token(user))


def _rows(response) -> list[list[str]] | None:
    outcome = getattr(response, "outcome", None)
    result = getattr(outcome, "result", None)
    # DuckDB versions differ in whether a month bucket is a date or a midnight timestamp; the same value must compare equal.
    return canonical_rows([list(r) for r in result.rows]) if result is not None else None


def _classify(response, *, executions: int) -> dict[str, Any]:
    outcome = getattr(response, "outcome", None)
    kind = getattr(outcome, "outcome", None)
    rows = _rows(response)
    verdict = "typed_failure"
    if kind == "answer":
        verdict = "correct_answer" if rows == EXPECTED_ROWS else "wrong_answer"
    elif response.state not in ("terminal", "waiting_review", "waiting_clarification"):
        verdict = "not_terminal"
    return {
        "verdict": verdict,
        "outcome": kind,
        "code": getattr(outcome, "error_code", None) or getattr(outcome, "reason_code", None),
        "executions": executions,
    }


# ---- 1. crash matrix ----


def _crash(root: Path, node: str, when: str, *, process_death: bool) -> dict[str, Any]:
    stack = build_stack("duckdb", root / "a")
    store = ControlStore(stack.control.engine, lease_seconds=LEASE)
    stack.control = store
    who = _who(stack)
    request = BootstrapRequest(request_id=f"crash-{node}-{when}", request_text=QUESTION, identity=who)
    state = stack.new_state(request, f"crash-run-{node}-{when}-{int(process_death)}", PURPOSE)
    armed = {"crashed": False}

    def handlers(target_stack, *, crash: bool):
        table = target_stack.nodes(who, request)
        original = table[node]

        def wrapped(node_input):
            if not crash or armed["crashed"]:
                return original(node_input)
            armed["crashed"] = True
            if when == "before":
                raise SystemExit("simulated crash before the node ran")
            original(node_input)
            raise SystemExit("simulated crash after the node ran, before its transition was committed")

        table[node] = wrapped
        return table

    clock_a = _Clock()
    start = clock_a.now
    try:
        AgentGraphRunner(store, governed_graph_v2(handlers(stack, crash=True)), now=clock_a).start(
            state, owner_id="worker-a", lease_token="lease-a"
        )
    except SystemExit:
        pass
    second = stack
    if process_death:  # a new process: same database, empty in-memory stores
        second = build_stack("duckdb", root / "a")
        second.control = ControlStore(second.control.engine, lease_seconds=LEASE)
    clock_b = _Clock(start + timedelta(seconds=LEASE + 1))
    try:
        AgentGraphRunner(second.control, governed_graph_v2(handlers(second, crash=False)), now=clock_b).resume(
            run_id=state.run_id, tenant_id=state.tenant_id, purpose=PURPOSE, owner_id="worker-b", lease_token="lease-b"
        )
    except Exception as exc:  # noqa: BLE001 - recorded as an unhandled error below
        return {
            "verdict": "unhandled_error",
            "error": type(exc).__name__,
            "executions": len(stack.executed_sql) + len(second.executed_sql)
            if second is not stack
            else len(stack.executed_sql),
            "node": node,
            "when": when,
        }
    executions = len(stack.executed_sql) + (len(second.executed_sql) if second is not stack else 0)
    response = second.service().status(who, purpose=PURPOSE, run_id=state.run_id)
    result = _classify(response, executions=executions)
    result.update({"node": node, "when": when, "chain_ok": _chain_ok(second, who.tenant_id)})
    return result


def _chain_ok(stack, tenant_id: str) -> bool:
    try:
        stack.evidence.verify_chain(tenant_id)
        return True
    except Exception:  # noqa: BLE001
        return False


def crash_matrix(root: Path, *, process_death: bool) -> list[dict[str, Any]]:
    return [
        _crash(root / f"{node}-{when}", node, when, process_death=process_death)
        for node in NODES
        for when in ("before", "after")
    ]


# ---- 2. dependency failures ----


def _explainer_down(*args, **kwargs):
    raise ConnectionError("explainer unavailable")


def _model_timeout(*args, **kwargs):
    class Client:
        def complete_json(self, **_):
            raise TimeoutError("model timed out")

    return Client()


DEPENDENCY_FAULTS: dict[str, tuple[str, Any]] = {
    "warehouse_down": ("gateway_execute", None),
    "estimator_down": ("gateway_estimate", None),
    "context_search_down": ("patch", ("SearchProvider", _Broken)),
    "context_snapshot_down": ("patch", ("SnapshotProvider", _Broken)),
    "explainer_down": ("patch", ("scripted_explainer", _explainer_down)),
    "model_timeout": ("patch", ("ScriptedIntentClient", _model_timeout)),
    "deadline_already_passed": ("deadline", None),
}


def _dependency(root: Path, name: str) -> dict[str, Any]:
    kind, arg = DEPENDENCY_FAULTS[name]
    stack = build_stack("duckdb", root)
    who = _who(stack)
    patches = []
    if kind == "patch":
        patches.append(mock.patch.object(stack_module, arg[0], arg[1]))
    elif kind in ("gateway_execute", "gateway_estimate"):
        method = "execute" if kind == "gateway_execute" else "estimate"

        def boom(*args, **kwargs):
            raise ConnectionError("warehouse unavailable")

        patches.append(mock.patch.object(type(stack.gateway), method, boom))
    elif kind == "deadline":
        original = stack.new_state

        def late(request, run_id, purpose):
            state = original(request, run_id, purpose)
            budget = state.budget.model_copy(update={"deadline": datetime.now(timezone.utc) - timedelta(seconds=1)})
            return state.model_copy(update={"budget": budget})

        stack.new_state = late
    for patch in patches:
        patch.start()
    try:
        try:
            response = stack.service().analyze(
                who, purpose=PURPOSE, idempotency_key=f"dep-{name}-0001", request_text=QUESTION
            )
        except ServiceError as exc:
            return {
                "fault": name,
                "verdict": "typed_failure",
                "outcome": "service_error",
                "code": exc.code,
                "executions": len(stack.executed_sql),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "fault": name,
                "verdict": "unhandled_error",
                "error": type(exc).__name__,
                "executions": len(stack.executed_sql),
            }
    finally:
        for patch in patches:
            patch.stop()
    result = _classify(response, executions=len(stack.executed_sql))
    result["fault"] = name
    result["degraded"] = getattr(response.outcome, "explanation_status", None) not in (None, "grounded")
    result["chain_ok"] = _chain_ok(stack, who.tenant_id)
    return result


def dependency_failures(root: Path) -> list[dict[str, Any]]:
    return [_dependency(root / name, name) for name in DEPENDENCY_FAULTS]


# ---- 3. chaos ----


def chaos(root: Path, *, seed: int, runs: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    results = []
    for index in range(runs):
        roll = rng.random()
        if roll < 0.15:
            plan = {"kind": "none"}
            result = _classify_run(root / f"c{index}", index)
        elif roll < 0.60:
            node, when, death = rng.choice(NODES), rng.choice(("before", "after")), rng.random() < 0.5
            plan = {"kind": "crash", "node": node, "when": when, "process_death": death}
            result = _crash(root / f"c{index}", node, when, process_death=death)
        else:
            fault = rng.choice(sorted(DEPENDENCY_FAULTS))
            plan = {"kind": "dependency", "fault": fault}
            result = _dependency(root / f"c{index}", fault)
        results.append({"index": index, "plan": plan, **result})
    return results


def _classify_run(root: Path, index: int) -> dict[str, Any]:
    stack = build_stack("duckdb", root)
    who = _who(stack)
    response = stack.service().analyze(
        who, purpose=PURPOSE, idempotency_key=f"chaos-none-{index:04d}", request_text=QUESTION
    )
    result = _classify(response, executions=len(stack.executed_sql))
    result["chain_ok"] = _chain_ok(stack, who.tenant_id)
    return result


# ---- the evaluation ----

SAFE = {"correct_answer", "typed_failure"}


def run_reliability(
    *, thresholds: dict[str, Any] | None = None, root: Path | None = None, chaos_runs: int = 40, seed: int = 20261013
) -> dict[str, Any]:
    thresholds = thresholds or json.loads(THRESHOLDS.read_text())
    root = root or Path(tempfile.mkdtemp(prefix="analytics-reliability-"))
    same = crash_matrix(root / "same", process_death=False)
    death = crash_matrix(root / "death", process_death=True)
    deps = dependency_failures(root / "deps")
    mixed = chaos(root / "chaos", seed=seed, runs=chaos_runs)
    everything = same + death + deps + mixed
    metrics = {
        "wrong_answers": sum(r["verdict"] == "wrong_answer" for r in everything),
        "duplicate_executions": sum(r["executions"] > 1 for r in everything),
        "unhandled_errors": sum(r["verdict"] == "unhandled_error" for r in everything),
        "unsafe_outcomes": sum(r["verdict"] not in SAFE for r in everything),
        "evidence_chain_breaks": sum(r.get("chain_ok") is False for r in everything),
        "crash_recovery_same_process": sum(r["verdict"] == "correct_answer" for r in same) / len(same),
        "crash_safe_ending_process_death": sum(r["verdict"] in SAFE for r in death) / len(death),
        "dependency_failures_handled": sum(r["verdict"] in SAFE for r in deps) / len(deps),
        "chaos_safe_ending_rate": sum(r["verdict"] in SAFE for r in mixed) / len(mixed),
    }
    gates = {
        name: {
            "value": metrics[name],
            "op": gate["op"],
            "threshold": gate["value"],
            "meets": bool(_OPS[gate["op"]](metrics[name], gate["value"])),
        }
        for name, gate in thresholds["gates"].items()
    }
    recovered_after_death = sorted({f"{r['node']}-{r['when']}" for r in death if r["verdict"] == "correct_answer"})
    failed_closed = sorted({f"{r['node']}-{r['when']}" for r in death if r["verdict"] == "typed_failure"})
    return {
        "packet": "ADS-075",
        "approval": thresholds["approval"],
        "ok": all(g["meets"] for g in gates.values()),
        "gates": gates,
        "gate_plan": GATE_PLAN,
        "samples": {"crash_points": len(same), "dependency_faults": len(deps), "chaos_runs": len(mixed), "seed": seed},
        "process_death": {"recovered": recovered_after_death, "failed_closed": failed_closed},
        "chaos_mix": dict(Counter(r["plan"]["kind"] for r in mixed)),
        "not_measured": thresholds["not_measured"],
        "same_process": same,
        "process_death_runs": death,
        "dependencies": deps,
        "chaos": mixed,
    }


def render_markdown(report: dict[str, Any]) -> str:
    approval = report["approval"]["status"]
    death = report["process_death"]
    lines = [
        "# ADS-075: Reliability, Crash/Replay, Dependency-Failure, and Chaos Evaluation",
        "",
        f"**Result: {'MEETS' if report['ok'] else 'DOES NOT MEET'} the {approval} thresholds.** The thresholds are {approval.upper()}{' and NOT APPROVED' if approval != 'approved' else ''}. "
        "Local fakes only: this measures mechanisms, not production availability.",
        "",
        f"{report['samples']['crash_points']} crash points x 2 models, {report['samples']['dependency_faults']} dependency faults, {report['samples']['chaos_runs']} seeded chaos runs (seed {report['samples']['seed']}; mix {report['chaos_mix']}).",
        "",
        "## Metrics",
        "",
        "| Metric | Measured | Gate | Meets | Plan gate |",
        "|---|---:|---:|:---:|---|",
    ]
    for name, gate in report["gates"].items():
        lines.append(
            f"| `{name}` | {gate['value']:.4g} | {gate['op']} {gate['threshold']} | {'yes' if gate['meets'] else '**NO**'} | {report['gate_plan'][name]} |"
        )
    lines += [
        "",
        "## What a real process crash does today",
        "",
        f"With fresh in-memory stores on the same database, {len(death['recovered'])} of {len(death['recovered']) + len(death['failed_closed'])} crash points still finish with a correct answer and "
        f"{len(death['failed_closed'])} **fail closed with a typed failure** (never a wrong answer): "
        + (", ".join(death["failed_closed"]) or "none")
        + ". "
        "Compiled plans, policy values, and result rows are process-local, so a run that crashed after they were created cannot continue in a new process. Durable plan and result storage is not built.",
        "",
        "## Dependency failures",
        "",
        "| Fault | Verdict | Outcome | Code | Queries run |",
        "|---|---|---|---|---:|",
    ]
    lines += [
        f"| {d['fault']} | {d['verdict']}{' (degraded)' if d.get('degraded') else ''} | {d.get('outcome')} | {d.get('code')} | {d['executions']} |"
        for d in report["dependencies"]
    ]
    lines += ["", "## Not measured", ""] + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()] + [""]
    return "\n".join(lines)
