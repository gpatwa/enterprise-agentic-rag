"""`python -m reference_stack smoke|up` (run from services/analytics-api with PYTHONPATH=.:../..)."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from reference_stack.smoke import run_all
from reference_stack.stack import build_stack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reference_stack", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke", help="run the DuckDB and PostgreSQL-emulation journeys")
    smoke.add_argument("--engine", choices=["duckdb", "postgres", "both"], default="both")
    smoke.add_argument("--json", action="store_true", help="print the full report as JSON")
    golden = sub.add_parser("golden", help="run the M4 golden suite and print or write the report")
    golden.add_argument("--write-report", metavar="DIR", help="write ADS-049-m4-golden-report.md/.json into DIR")
    triage = sub.add_parser("triage", help="run the ADS-051 triage corpus and print or write the report")
    triage.add_argument("--write-report", metavar="DIR")
    up = sub.add_parser("up", help="serve the v2 API locally with this stack (loopback only)")
    up.add_argument("--engine", choices=["duckdb", "postgres"], default="duckdb")
    up.add_argument("--port", type=int, default=8095)
    args = parser.parse_args(argv)
    logging.disable(logging.INFO)

    if args.command == "smoke":
        engines = ("duckdb", "postgres") if args.engine == "both" else (args.engine,)
        report = run_all(engines)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            for journey in report["journeys"]:
                print(f"[{'PASS' if journey['ok'] else 'FAIL'}] {journey['engine']}")
                for step in journey["steps"]:
                    print(
                        f"  {'ok  ' if step['ok'] else 'FAIL'} {step['name']}{'' if step['ok'] else ': ' + step['detail']}"
                    )
            if report["cross_dialect_rows_identical"] is not None:
                print(f"cross-dialect rows identical: {report['cross_dialect_rows_identical']}")
            print("RESULT:", "PASS" if report["ok"] else "FAIL")
        return 0 if report["ok"] else 1

    if args.command == "triage":
        import tempfile
        from pathlib import Path

        from reference_stack.triage_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-triage-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-051-triage-report.md").write_text(markdown)
            (target / "ADS-051-triage-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    if args.command == "golden":
        from pathlib import Path

        from reference_stack.golden import render_markdown, run_golden

        report = run_golden()
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-049-m4-golden-report.md").write_text(markdown)
            (target / "ADS-049-m4-golden-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; "
            f"meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    import uvicorn

    stack = build_stack(args.engine)
    print(f"Reference stack ({args.engine}, fakes only) on http://127.0.0.1:{args.port}", flush=True)
    print("Locally signed test tokens, valid 60 minutes (accepted only by this process):", flush=True)
    print(f"  requester: {stack.token('requester')}", flush=True)
    print(f"  reviewer:  {stack.token('reviewer')}", flush=True)
    uvicorn.run(stack.app(), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
