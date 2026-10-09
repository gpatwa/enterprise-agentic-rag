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
