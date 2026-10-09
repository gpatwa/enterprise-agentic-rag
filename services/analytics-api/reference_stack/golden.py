"""Milestone-4 golden suite and report (ADS-049).

A pinned corpus is run through the reference stack on both dialects, expected rows were computed
independently in plain Python, and the measured metrics are compared with *proposed* thresholds.
The thresholds are unapproved: this module reports against them but never records approval, and
a report only ever says "meets proposed thresholds", never that a gate passed.
"""

from __future__ import annotations

import hashlib
import json
import math
import operator
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reference_stack.fakes import PURPOSE
from reference_stack.smoke import seal_run
from reference_stack.stack import Engine, ReferenceStack, build_stack

HERE = Path(__file__).parent / "golden"
CORPUS = HERE / "golden-suite-v1.json"
THRESHOLDS = HERE / "m4-thresholds.proposed.json"
URL = "/api/v2/analytics"
LATENCY_REPEATS = 5
_OPS = {">=": operator.ge, "<=": operator.le}


class SuiteLockError(RuntimeError):
    """The corpus no longer matches the digest the thresholds were drafted against."""


@dataclass
class CaseResult:
    case_id: str
    engine: str
    kind: str
    passed: bool
    detail: str = ""


@dataclass
class Observations:
    cases: list[CaseResult] = field(default_factory=list)
    answered: int = 0
    sealed: int = 0
    replay_ok: int = 0
    budget_overruns: int = 0
    raw_sql_executed: int = 0
    latencies: list[float] = field(default_factory=list)
    overheads_ms: list[float] = field(default_factory=list)
    rows_by_case: dict[str, dict[str, list]] = field(default_factory=dict)


def load_suite() -> tuple[dict, dict]:
    raw = CORPUS.read_bytes()
    thresholds = json.loads(THRESHOLDS.read_text())
    if hashlib.sha256(raw).hexdigest() != thresholds["corpus_sha256"]:
        raise SuiteLockError("golden corpus changed without updating the pinned digest in the thresholds file")
    return json.loads(raw), thresholds


def _headers(stack: ReferenceStack, user: str, key: str | None = None, **kwargs) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {stack.token(user, **kwargs)}"}
    return {**headers, "Idempotency-Key": key} if key else headers


def _post(client, stack, question, key, **kwargs):
    return client.post(
        f"{URL}/analyze",
        json={"request_text": question, "purpose": PURPOSE},
        headers=_headers(stack, "requester", key, **kwargs),
    )


def _within_budget(stack: ReferenceStack, run_id: str) -> bool:
    state = stack.control.load_latest_checkpoint(run_id=run_id, tenant_id="tenant-a", purpose=PURPOSE)
    return state.transition_count <= state.budget.max_transitions and state.status in {"terminal", "waiting_approval"}


def _answer_case(stack, client, case, engine, obs: Observations) -> None:
    key = f"golden-{case['id']}-0"
    stack.timings.clear()
    started = time.perf_counter()
    first = _post(client, stack, case["question"], key).json()
    obs.latencies.append(time.perf_counter() - started)
    obs.overheads_ms.append(sum(seconds for _, seconds in stack.timings) * 1000)
    outcome = first.get("outcome") or {}
    rows = (outcome.get("result") or {}).get("rows")
    expected = case["expect_rows"]
    passed = (
        outcome.get("outcome") == "answer"
        and rows == expected
        and len(outcome["result"]["columns"]) == case["expect_columns"]
    )
    detail = "" if passed else f"expected {expected}, got {rows if rows is not None else outcome.get('outcome')}"
    if passed:
        obs.answered += 1
        obs.rows_by_case.setdefault(case["id"], {})[engine] = rows
        obs.sealed += bool(seal_run(stack, first["run_id"]))
        replay = _post(client, stack, case["question"], key).json()
        obs.replay_ok += int(
            replay["run_id"] == first["run_id"]
            and replay["outcome"]["evidence"]["result_fingerprint"] == outcome["evidence"]["result_fingerprint"]
        )
        for n in range(1, LATENCY_REPEATS):
            stack.timings.clear()
            started = time.perf_counter()
            again = _post(client, stack, case["question"], f"golden-{case['id']}-{n}").json()
            obs.latencies.append(time.perf_counter() - started)
            obs.overheads_ms.append(sum(seconds for _, seconds in stack.timings) * 1000)
            if (again.get("outcome") or {}).get("result", {}).get("rows") != expected:
                passed, detail = False, f"repeat {n} returned different rows"
    obs.budget_overruns += 0 if _within_budget(stack, first["run_id"]) else 1
    obs.cases.append(CaseResult(case["id"], engine, case["kind"], passed, detail))


def _refusal_case(stack, client, case, engine, obs: Observations) -> None:
    before = len(stack.executed_sql)
    response = _post(client, stack, case["question"], f"golden-{case['id']}-0")
    body = response.json()
    outcome = body.get("outcome") or {}
    refused = response.status_code >= 400 or outcome.get("outcome") in {"failed", "refuse"}
    no_data = "result" not in outcome and len(stack.executed_sql) == before
    passed = refused and no_data
    if body.get("run_id"):
        obs.budget_overruns += 0 if _within_budget(stack, body["run_id"]) else 1
    obs.cases.append(
        CaseResult(
            case["id"],
            engine,
            case["kind"],
            passed,
            "" if passed else f"{response.status_code} {outcome.get('outcome')}",
        )
    )


def _tenant_case(stack, client, case, engine, obs: Observations, known_run: str | None) -> None:
    before = len(stack.executed_sql)
    foreign = _post(client, stack, case["question"], "golden-T01-0", tenant="tenant-b")
    leak = foreign.status_code == 200 and "result" in (foreign.json().get("outcome") or {})
    read = (
        client.get(
            f"{URL}/runs/{known_run}",
            params={"purpose": PURPOSE},
            headers=_headers(stack, "requester", tenant="tenant-b"),
        )
        if known_run
        else None
    )
    leak = leak or (read is not None and read.status_code == 200)
    passed = not leak and len(stack.executed_sql) == before and foreign.status_code in {403, 503}
    obs.cases.append(
        CaseResult(
            case["id"], engine, case["kind"], passed, "" if passed else f"status {foreign.status_code}, leak={leak}"
        )
    )


def _pause_case(stack, client, case, engine, obs: Observations, expect_state: str, expect_outcome: str) -> None:
    before = len(stack.executed_sql)
    response = _post(client, stack, case["question"], f"golden-{case['id']}-0").json()
    outcome = response.get("outcome") or {}
    passed = (
        response.get("state") == expect_state and outcome.get("outcome") == expect_outcome and "result" not in outcome
    )
    passed = passed and not any(sql for sql in stack.executed_sql[before:])
    if response.get("run_id"):
        obs.budget_overruns += 0 if _within_budget(stack, response["run_id"]) else 1
    obs.cases.append(CaseResult(case["id"], engine, case["kind"], passed, "" if passed else str(response)[:160]))


def run_engine(engine: Engine, suite: dict, obs: Observations) -> None:
    stacks = {
        "main": build_stack(engine),
        "denied": build_stack(engine, denied=True),
        "ambiguous": build_stack(engine, ambiguous=True),
        "review": build_stack(engine, review_threshold=1e-9),
    }
    clients = {name: TestClient(stack.app()) for name, stack in stacks.items()}
    main, client = stacks["main"], clients["main"]
    known_run: str | None = None
    for case in suite["cases"]:
        kind = case["kind"]
        if kind == "answer":
            _answer_case(main, client, case, engine, obs)
            known_run = known_run or _post(client, main, case["question"], f"golden-{case['id']}-0").json().get(
                "run_id"
            )
        elif kind == "refuse_no_execution":
            _refusal_case(main, client, case, engine, obs)
        elif kind == "policy_denied":
            _refusal_case(stacks["denied"], clients["denied"], case, engine, obs)
        elif kind == "tenant_isolation":
            _tenant_case(main, client, case, engine, obs, known_run)
        elif kind == "clarify":
            _pause_case(
                stacks["ambiguous"], clients["ambiguous"], case, engine, obs, "waiting_clarification", "clarify"
            )
        elif kind == "review":
            _pause_case(stacks["review"], clients["review"], case, engine, obs, "waiting_review", "review")
        else:
            obs.cases.append(CaseResult(case["id"], engine, kind, False, "unknown case kind"))
    for stack in stacks.values():
        obs.raw_sql_executed += len([sql for sql in stack.executed_sql if sql not in stack.compiled_sql])


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)] if ordered else float("nan")


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def compute_metrics(suite: dict, obs: Observations, engines: tuple[str, ...]) -> dict[str, float]:
    def cases(pred) -> list[CaseResult]:
        return [r for r in obs.cases if pred(r)]

    ids = {c["id"]: c for c in suite["cases"]}
    answers = cases(lambda r: r.kind == "answer")
    p0 = [r for r in answers if ids[r.case_id].get("p0")]
    refusals = cases(lambda r: r.kind in {"refuse_no_execution", "policy_denied", "tenant_isolation"})
    pauses = cases(lambda r: r.kind in {"clarify", "review"})
    answer_ids = [c["id"] for c in suite["cases"] if c["kind"] == "answer"]
    both = [i for i in answer_ids if len(obs.rows_by_case.get(i, {})) == len(engines)]
    equal = [i for i in both if len({json.dumps(v) for v in obs.rows_by_case[i].values()}) == 1]
    protected = cases(lambda r: r.kind in {"policy_denied", "tenant_isolation"})
    return {
        "p0_result_equivalence": _ratio(sum(r.passed for r in p0), len(p0)),
        "answer_result_equivalence": _ratio(sum(r.passed for r in answers), len(answers)),
        "refusal_recall": _ratio(sum(r.passed for r in refusals), len(refusals)),
        "clarify_or_review_recall": _ratio(sum(r.passed for r in pauses), len(pauses)),
        "policy_and_tenant_violations": sum(not r.passed for r in protected),
        "raw_model_sql_executed": obs.raw_sql_executed,
        "evidence_completeness": _ratio(obs.sealed, obs.answered),
        "replay_fingerprint_equivalence": _ratio(obs.replay_ok, obs.answered),
        "dialect_result_equivalence": _ratio(len(equal), len(answer_ids)) if len(engines) > 1 else 0.0,
        "budget_overruns": obs.budget_overruns,
        "p95_answer_latency_seconds": _p95(obs.latencies),
        "p95_compile_policy_overhead_ms": _p95(obs.overheads_ms),
    }


def evaluate(metrics: dict[str, float], thresholds: dict) -> dict[str, dict[str, Any]]:
    out = {}
    for name, gate in thresholds["gates"].items():
        value = metrics[name]
        out[name] = {
            "value": value,
            "op": gate["op"],
            "threshold": gate["value"],
            "meets": bool(_OPS[gate["op"]](value, gate["value"])),
        }
    return out


def run_golden(engines: tuple[Engine, ...] = ("duckdb", "postgres")) -> dict[str, Any]:
    suite, thresholds = load_suite()
    obs = Observations()
    for engine in engines:
        run_engine(engine, suite, obs)
    metrics = compute_metrics(suite, obs, engines)
    gates = evaluate(metrics, thresholds)
    return {
        "suite_version": suite["suite_version"],
        "corpus_sha256": thresholds["corpus_sha256"],
        "engines": list(engines),
        "approval": thresholds["approval"],
        "meets_proposed_thresholds": all(g["meets"] for g in gates.values()),
        "gates": gates,
        "gate_definitions": thresholds["gates"],
        "not_measured_at_m4": thresholds["not_measured_at_m4"],
        "samples": {"latency": len(obs.latencies), "overhead": len(obs.overheads_ms), "answered_runs": obs.answered},
        "cases": [asdict(r) for r in obs.cases],
    }


def render_markdown(report: dict[str, Any], *, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    verdict = (
        "MEETS the proposed thresholds"
        if report["meets_proposed_thresholds"]
        else "DOES NOT MEET the proposed thresholds"
    )
    lines = [
        "# ADS-049: Milestone-4 Golden Report",
        "",
        f"Generated {stamp} by `make analytics-golden`. Suite `{report['suite_version']}`, corpus `{report['corpus_sha256'][:12]}`, "
        f"engines: {', '.join(report['engines'])}.",
        "",
        f"**Result: {verdict}. The thresholds are PROPOSED and NOT APPROVED** (approval status: "
        f"`{report['approval']['status']}`). This is not a gate pass and does not record or imply the M4 `local_demo_review` approval.",
        "",
        "## Scope and limits",
        "",
        "- Scripted model (three phrasings plus adversarial inputs), seeded 100-row table, DuckDB, and an **emulated** PostgreSQL. "
        "Nothing here measures language understanding, real PostgreSQL behavior, a live index, or a real model.",
        "- Expected rows were computed independently in plain Python from the seed formula, not from the system under test.",
        f"- Latency/overhead percentiles come from small samples ({report['samples']['latency']} answered calls); treat them as a smoke signal.",
        "",
        "## Metrics against proposed thresholds",
        "",
        "| Metric | Measured | Proposed gate | Meets | Plan gate |",
        "|---|---:|---:|:---:|---|",
    ]
    for name, gate in report["gates"].items():
        value = gate["value"]
        shown = f"{value:.4g}" if isinstance(value, float) else str(value)
        lines.append(
            f"| `{name}` | {shown} | {gate['op']} {gate['threshold']} | {'yes' if gate['meets'] else '**NO**'} | "
            f"{report['gate_definitions'][name]['plan_gate']} |"
        )
    lines += ["", "## Cases", "", "| Case | Engine | Kind | Result | Detail |", "|---|---|---|:---:|---|"]
    for case in report["cases"]:
        lines.append(
            f"| {case['case_id']} | {case['engine']} | {case['kind']} | {'pass' if case['passed'] else '**FAIL**'} | {case['detail']} |"
        )
    lines += ["", "## Not measured at M4", ""]
    lines += [f"- **{name}**: {reason}" for name, reason in report["not_measured_at_m4"].items()]
    lines += [
        "",
        "## Decisions that remain with the user",
        "",
        "- Approve, amend, or reject the proposed thresholds (`reference_stack/golden/m4-thresholds.proposed.json`).",
        "- The M4 `local_demo_review` human gate, and independent review of ADS-040 to ADS-049.",
        "- M1 semantic certification and any live PostgreSQL/OpenSearch/OpenMetadata validation.",
        "",
    ]
    return "\n".join(lines)
