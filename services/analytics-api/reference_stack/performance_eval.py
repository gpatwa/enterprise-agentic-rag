"""ADS-076: latency, concurrency, token, warehouse, and infrastructure cost evaluation (fakes only).

Measured on the local reference stack (scripted model, DuckDB, an emulated PostgreSQL, SQLite control store): warm and concurrent answer
latency against the plan section 10 gates, deterministic compile/policy overhead, tokens per intent, warehouse cost units per answer,
and tenant fairness under a scripted overload using the ADS-066 simulator. Unit economics apply an ASSUMED price table from the
thresholds file: the prices are placeholders chosen by the implementing agent, not quotes, and the plan says latency and cost must be
re-baselined for the selected staging model and warehouse. Thresholds are PROPOSED until the user approves them.
"""

from __future__ import annotations

import json
import math
import resource
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest import mock

from app.quotas import QuotaManager
from app.quotas.simulation import FakeClock, simulate
from packages.platform_contracts.quotas import QuotaPolicy
from reference_stack import m7_corpus as corpus_module
from reference_stack.golden import canonical_rows
from reference_stack import stack as stack_module
from reference_stack.stack import build_stack

HERE = Path(__file__).parent / "m7"
THRESHOLDS = HERE / "performance-thresholds.proposed.json"
SERVICE_ROOT = Path(__file__).resolve().parent.parent
PURPOSE = "analytics"
QUESTIONS = {
    "What is total revenue": corpus_module.expected("total")[1],
    "Revenue by status": corpus_module.expected("by_status")[1],
    "Show monthly revenue": corpus_module.expected("monthly_paid")[1],
    "Top revenue status": corpus_module.expected("top_status")[1],
}
ORDER = list(QUESTIONS)
_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
GATE_PLAN = {
    "p95_warm_latency_seconds": "P95 warm answer latency, local reference data <= 8 seconds",
    "p95_concurrent_latency_seconds": "P95 at target concurrency <= 8 seconds",
    "p95_compile_policy_overhead_ms": "P95 deterministic compile/policy overhead <= 250 ms",
    "concurrent_errors_or_wrong_rows": "No errors or wrong rows under concurrency: 0",
    "prompt_tokens_per_intent_max": "Context tokens per intent stay within the run's context budget",
    "cost_per_answer_usd": "Unit economics: assumed cost per answered question within the proposed ceiling",
    "warehouse_cost_units_per_answer": "Warehouse cost units per answer (mean over the question mix) within the proposed ceiling",
    "answers_per_tenant_day": "The proposed daily cost budget affords a tenant at least this many answers a day",
    "quiet_tenant_denials": "A noisy neighbour does not deny a quiet tenant: 0",
    "noisy_tenant_over_quota": "A tenant above its quota is held to it: 0 admissions above the allowed",
}


def _p(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)] if ordered else float("nan")


def _tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


class _RecordingModel:
    """Wraps the scripted model and records the size of each prompt and reply."""

    sizes: list[tuple[int, int]] = []

    def __init__(self, inner_class):
        self.inner_class = inner_class

    def __call__(self, *args, **kwargs):
        inner = self.inner_class(*args, **kwargs)
        sizes = self.sizes

        class Recorded:
            def complete_json(self, *, prompt, schema, max_tokens):
                reply = inner.complete_json(prompt=prompt, schema=schema, max_tokens=max_tokens)
                sizes.append((_tokens(prompt), _tokens(json.dumps(reply))))
                return reply

        return Recorded()


def _ask(service, who, key: str, question: str) -> tuple[float, bool]:
    started = time.perf_counter()
    response = service.analyze(who, purpose=PURPOSE, idempotency_key=key, request_text=question)
    elapsed = time.perf_counter() - started
    outcome = response.outcome
    rows = canonical_rows([list(r) for r in outcome.result.rows]) if getattr(outcome, "result", None) else None
    return elapsed, rows == QUESTIONS[question]


def measure_engine(engine: str, root: Path, *, warm: int, workers: int, per_worker: int) -> dict[str, Any]:
    _RecordingModel.sizes = []
    stack = build_stack(engine, root)
    who = stack.verifier().verify(stack.token("requester"))
    service = stack.service()
    with mock.patch.object(stack_module, "ScriptedIntentClient", _RecordingModel(stack_module.ScriptedIntentClient)):
        for i in range(4):  # warm-up: first calls pay for imports and caches
            _ask(service, who, f"warm-{engine}-{i:05d}", ORDER[i % 4])
        stack.timings.clear()
        warm_runs = [_ask(service, who, f"seq-{engine}-{i:05d}", ORDER[i % 4]) for i in range(warm)]
        overhead_ms = [seconds * 1000 for _, seconds in stack.timings]
        per_run_overhead = [
            sum(s for _, s in stack.timings[i : i + 2]) * 1000 for i in range(0, len(stack.timings) - 1, 2)
        ]
        started = time.perf_counter()

        def worker(w: int) -> list[tuple[float, bool]]:
            out = []
            for i in range(per_worker):
                try:
                    out.append(_ask(service, who, f"con-{engine}-{w:02d}-{i:04d}", ORDER[(w + i) % 4]))
                except Exception:  # noqa: BLE001 - counted as an error below
                    out.append((0.0, False))
            return out

        with ThreadPoolExecutor(workers) as pool:
            concurrent = [r for chunk in pool.map(worker, range(workers)) for r in chunk]
        wall = time.perf_counter() - started
    prompt_tokens = [p for p, _ in _RecordingModel.sizes]
    completion_tokens = [c for _, c in _RecordingModel.sizes]
    unit_costs = [
        float(
            stack.control.load_latest_checkpoint(
                run_id=service.run_id_for(who, PURPOSE, f"seq-{engine}-{i:05d}"),
                tenant_id=who.tenant_id,
                purpose=PURPOSE,
            ).cost_decision["estimated_cost_units"]
        )
        for i in range(4)
    ]
    return {
        "engine": engine,
        "warm_latencies": [t for t, _ in warm_runs],
        "warm_wrong": sum(not ok for _, ok in warm_runs),
        "concurrent_latencies": [t for t, _ in concurrent],
        "concurrent_bad": sum(not ok for _, ok in concurrent),
        "concurrent_throughput": len(concurrent) / wall,
        "overhead_ms": per_run_overhead or overhead_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_units": unit_costs,
    }


def fairness(policy_path: Path = SERVICE_ROOT / "quotas" / "quota-policy.proposed.json") -> dict[str, Any]:
    policy = QuotaPolicy.model_validate_json(policy_path.read_text())
    clock = FakeClock()
    manager = QuotaManager(policy, clock=clock)
    duration = 120
    noisy = [(t / 10.0, "noisy", 0.5, 20.0) for t in range(duration * 10)]  # 10 requests per second
    quiet = [(float(t), "quiet", 0.5, 20.0) for t in range(duration)]  # 1 per second, well inside its quota
    result = simulate(manager, clock, noisy + quiet)
    quota = policy.quota_for("noisy")
    allowed = quota.burst + quota.requests_per_minute * duration / 60.0 + quota.max_concurrent_runs
    return {
        "duration_seconds": duration,
        "noisy": {
            "offered": len(noisy),
            "admitted": result.admitted["noisy"],
            "denied": dict(result.denied["noisy"]),
            "allowed_at_most": allowed,
        },
        "quiet": {
            "offered": len(quiet),
            "admitted": result.admitted["quiet"],
            "denied": {k: dict(v) for k, v in result.denied.items()}.get("quiet", {}),
        },
    }


def run_performance(
    *,
    thresholds: dict[str, Any] | None = None,
    root: Path | None = None,
    warm: int = 100,
    workers: int = 8,
    per_worker: int = 20,
) -> dict[str, Any]:
    thresholds = thresholds or json.loads(THRESHOLDS.read_text())
    root = root or Path(tempfile.mkdtemp(prefix="analytics-performance-"))
    engines = {
        engine: measure_engine(engine, root / engine, warm=warm, workers=workers, per_worker=per_worker)
        for engine in ("duckdb", "postgres")
    }
    warm_all = [t for e in engines.values() for t in e["warm_latencies"]]
    con_all = [t for e in engines.values() for t in e["concurrent_latencies"]]
    over = [t for e in engines.values() for t in e["overhead_ms"]]
    prompts = [t for e in engines.values() for t in e["prompt_tokens"]]
    completions = [t for e in engines.values() for t in e["completion_tokens"]]
    prices = thresholds["assumed_prices"]
    unit_costs = [c for e in engines.values() for c in e["cost_units"]]
    cost_units = statistics_mean(unit_costs)
    daily_budget = QuotaPolicy.model_validate_json(
        (SERVICE_ROOT / "quotas" / "quota-policy.proposed.json").read_text()
    ).default.daily_cost_units
    cost_usd = (
        statistics_mean(prompts) * prices["usd_per_million_input_tokens"] / 1e6
        + statistics_mean(completions) * prices["usd_per_million_output_tokens"] / 1e6
        + cost_units * prices["usd_per_warehouse_cost_unit"]
    )
    shared = fairness()
    metrics = {
        "p95_warm_latency_seconds": _p(warm_all, 0.95),
        "p95_concurrent_latency_seconds": _p(con_all, 0.95),
        "p95_compile_policy_overhead_ms": _p(over, 0.95),
        "concurrent_errors_or_wrong_rows": sum(e["concurrent_bad"] + e["warm_wrong"] for e in engines.values()),
        "prompt_tokens_per_intent_max": max(prompts),
        "cost_per_answer_usd": cost_usd,
        "warehouse_cost_units_per_answer": cost_units,
        "answers_per_tenant_day": daily_budget / cost_units,
        "quiet_tenant_denials": sum(shared["quiet"]["denied"].values()) if shared["quiet"]["denied"] else 0,
        "noisy_tenant_over_quota": max(0, shared["noisy"]["admitted"] - math.ceil(shared["noisy"]["allowed_at_most"])),
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
    return {
        "packet": "ADS-076",
        "approval": thresholds["approval"],
        "ok": all(g["meets"] for g in gates.values()),
        "gates": gates,
        "gate_plan": GATE_PLAN,
        "samples": {
            "warm_requests": len(warm_all),
            "concurrent_requests": len(con_all),
            "workers": workers,
            "throughput_per_second": {e["engine"]: round(e["concurrent_throughput"], 1) for e in engines.values()},
            "latency_seconds": {"p50": _p(warm_all, 0.5), "p95": _p(warm_all, 0.95), "p99": _p(warm_all, 0.99)},
            "cost_units_range": [min(unit_costs), max(unit_costs)],
            "daily_cost_units": daily_budget,
            "mean_prompt_tokens": statistics_mean(prompts),
            "mean_completion_tokens": statistics_mean(completions),
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1),
        },
        "assumed_prices": prices,
        "fairness": shared,
        "not_measured": thresholds["not_measured"],
    }


def statistics_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def render_markdown(report: dict[str, Any]) -> str:
    approval = report["approval"]["status"]
    s = report["samples"]
    lines = [
        "# ADS-076: Latency, Concurrency, Token, Warehouse, and Infrastructure Cost Evaluation",
        "",
        f"**Result: {'MEETS' if report['ok'] else 'DOES NOT MEET'} the {approval} thresholds.** The thresholds are {approval.upper()}{' and NOT APPROVED' if approval != 'approved' else ''}. "
        "Measured on a scripted model, local DuckDB, an emulated PostgreSQL, and a SQLite control store: **these numbers say nothing about a real model or warehouse**, and the plan requires latency and cost to be re-baselined for the staging stack.",
        "",
        f"{s['warm_requests']} warm requests, {s['concurrent_requests']} concurrent requests ({s['workers']} workers per engine), throughput {s['throughput_per_second']} requests/s, "
        f"warehouse cost units per answer {s['cost_units_range'][0]:g} to {s['cost_units_range'][1]:g} (uncalibrated, per dialect) against a proposed daily budget of {s['daily_cost_units']:g}; "
        f"warm latency p50 {s['latency_seconds']['p50'] * 1000:.0f} ms, p95 {s['latency_seconds']['p95'] * 1000:.0f} ms, p99 {s['latency_seconds']['p99'] * 1000:.0f} ms; mean tokens per intent {s['mean_prompt_tokens']:.0f} in / {s['mean_completion_tokens']:.0f} out; peak RSS {s['peak_rss_mb']} MB.",
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
    f = report["fairness"]
    lines += (
        [
            "",
            "## Tenant fairness under overload (ADS-066 simulator)",
            "",
            f"In {f['duration_seconds']} simulated seconds the noisy tenant offered {f['noisy']['offered']} requests and was admitted {f['noisy']['admitted']} (at most {f['noisy']['allowed_at_most']:.0f} allowed; denied {f['noisy']['denied']}); "
            f"the quiet tenant offered {f['quiet']['offered']}, was admitted {f['quiet']['admitted']}, denied {f['quiet']['denied'] or 'none'}.",
            "",
            "## Assumed prices (placeholders, not quotes)",
            "",
            f"`{report['assumed_prices']}`",
            "",
            "## Not measured",
            "",
        ]
        + [f"- **{k}**: {v}" for k, v in report["not_measured"].items()]
        + [""]
    )
    return "\n".join(lines)
