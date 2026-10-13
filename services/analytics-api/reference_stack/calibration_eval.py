"""M7-H4: cost-unit calibration mechanism checks and a local measurement (fakes only; NOT a warehouse calibration).

The mechanism is checked deterministically (a known scale is recovered; too few, constant, or non-predictive samples are refused; an
unapproved or non-production calibration is never applied). A local measurement times the four reference questions on local DuckDB and the
emulated PostgreSQL and reports how well the raw estimates predict elapsed time there; it is informational and is never stored as a
calibration: real warehouse samples are needed, and a person must approve the result.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from app.execution.calibration import CalibrationError, calibrated_units, fit_calibration
from packages.platform_contracts.cost_calibration import CalibrationApproval, CostSample
from reference_stack import performance_eval
from reference_stack.stack import build_stack


def mechanism_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    samples = [CostSample(dialect="d", estimated_units=float(u), observed=3.0 * u + 7.0) for u in range(10, 60, 4)]
    fit = fit_calibration(
        samples, version="t", unit="ms", calibrated_against="synthetic", valid_for_production=True
    ).fits["d"]
    check(
        "a known scale and offset are recovered",
        abs(fit.scale - 3.0) < 1e-9 and abs(fit.offset - 7.0) < 1e-9 and fit.r_squared > 0.999999,
    )
    for name, rows, code in (
        ("too few samples are refused", samples[:3], "too_few_samples"),
        (
            "constant estimates are refused",
            [CostSample(dialect="d", estimated_units=5.0, observed=float(i + 1)) for i in range(12)],
            "estimates_do_not_vary",
        ),
        (
            "estimates that do not predict cost are refused",
            [CostSample(dialect="d", estimated_units=float(i + 1), observed=float(100 - i)) for i in range(12)],
            "estimates_do_not_predict_cost",
        ),
    ):
        try:
            fit_calibration(rows, version="t", unit="ms", calibrated_against="x", valid_for_production=True)
            check(name, False, "accepted")
        except CalibrationError as exc:
            check(name, exc.code.startswith(code), exc.code)
    proposed = fit_calibration(
        samples, version="t", unit="ms", calibrated_against="synthetic", valid_for_production=True
    )
    check("a proposed calibration is not applied", calibrated_units(proposed, "d", 20.0) == (20.0, False))
    local = proposed.model_copy(
        update={
            "approval": proposed.approval.model_copy(
                update={"status": "approved", "approved_by": "p", "approved_at": "2026-10-13"}
            ),
            "valid_for_production": False,
        }
    )
    check(
        "an approved but non-production calibration is not applied", calibrated_units(local, "d", 20.0) == (20.0, False)
    )
    approved = proposed.model_copy(
        update={
            "approval": proposed.approval.model_copy(
                update={"status": "approved", "approved_by": "p", "approved_at": "2026-10-13"}
            )
        }
    )
    check(
        "an approved production calibration is applied for its own dialect only",
        calibrated_units(approved, "d", 20.0) == (67.0, True)
        and calibrated_units(approved, "other", 20.0) == (20.0, False),
    )
    try:
        CalibrationApproval(status="approved")
        check("approval without a named person is refused", False)
    except ValueError:
        check("approval without a named person is refused", True)
    return checks


def local_measurement(root: Path | None = None, *, repeats: int = 30) -> dict[str, Any]:
    """Time the reference questions locally and compare with the raw estimates. Informational only."""
    root = root or Path(tempfile.mkdtemp(prefix="analytics-calibration-"))
    out: dict[str, Any] = {}
    for engine in ("duckdb", "postgres"):
        stack = build_stack(engine, root / engine)
        who = stack.verifier().verify(stack.token("requester"))
        service = stack.service()
        rows = []
        for i, question in enumerate(performance_eval.ORDER):
            response = service.analyze(
                who, purpose="analytics", idempotency_key=f"cal-{engine}-{i:05d}", request_text=question
            )
            state = stack.control.load_latest_checkpoint(
                run_id=response.run_id, tenant_id=who.tenant_id, purpose="analytics"
            )
            plan = stack.plans.get(who.tenant_id, response.run_id, state.compiled_plan_reference)
            elapsed = []
            for _ in range(repeats):
                started = time.perf_counter()
                stack.gateway.execute(
                    plan, limits=__import__("app.execution", fromlist=["ExecutionLimits"]).ExecutionLimits()
                )
                elapsed.append((time.perf_counter() - started) * 1000)
            rows.append(
                {
                    "question": question,
                    "estimated_units": float(state.cost_decision["estimated_cost_units"]),
                    "median_ms": sorted(elapsed)[len(elapsed) // 2],
                }
            )
        out[engine] = rows
    return out


def run_calibration() -> dict[str, Any]:
    checks = mechanism_checks()
    return {
        "packet": "M7-H4",
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "local_measurement": local_measurement(),
        "limits": [
            "This is not a warehouse calibration. Real warehouse samples (estimated units and the observed cost in the chosen unit) are needed, and a person must approve the fitted calibration.",
            "Local DuckDB over 100 rows and an emulated PostgreSQL do not stand in for the target warehouse.",
            "No calibration is applied anywhere by default; the quota gate answers_per_tenant_day in ADS-076 is therefore unchanged.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M7-H4: Cost-unit calibration mechanism",
        "",
        f"**Mechanism checks: {'all pass' if report['ok'] else 'FAIL'}.** This is not a warehouse calibration and no calibration is applied by default.",
        "",
        "| Check | OK | Detail |",
        "|---|:---:|---|",
    ] + [f"| {c['check']} | {'yes' if c['ok'] else '**NO**'} | {c['detail']} |" for c in report["checks"]]
    lines += [
        "",
        "## Local measurement (informational)",
        "",
        "| Engine | Question | Estimated units | Median ms |",
        "|---|---|---:|---:|",
    ]
    for engine, rows in report["local_measurement"].items():
        lines += [f"| {engine} | {r['question']} | {r['estimated_units']:g} | {r['median_ms']:.2f} |" for r in rows]
    lines += ["", "## Limits", ""] + [f"- {item}" for item in report["limits"]] + [""]
    return "\n".join(lines)


if (
    __name__ == "__main__"
):  # `python -m reference_stack.calibration_eval samples.json` fits PROPOSED calibrations from real samples
    import sys

    if len(sys.argv) == 2:
        rows = [CostSample.model_validate(r) for r in json.loads(Path(sys.argv[1]).read_text())]
        print(
            fit_calibration(
                rows,
                version="proposed",
                unit="set-by-owner",
                calibrated_against="set-by-owner",
                valid_for_production=False,
            ).model_dump_json(indent=2)
        )
    else:
        print(render_markdown(run_calibration()))
