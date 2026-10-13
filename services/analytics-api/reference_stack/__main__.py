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
    proposals = sub.add_parser("proposals", help="run the ADS-052 proposal corpus and print or write the report")
    proposals.add_argument("--write-report", metavar="DIR")
    dbt = sub.add_parser("dbt", help="run the ADS-053 dbt proposal corpus and print or write the report")
    dbt.add_argument("--write-report", metavar="DIR")
    prompts = sub.add_parser("prompts", help="run the ADS-054 prompt registry corpus and print or write the report")
    prompts.add_argument("--write-report", metavar="DIR")
    review = sub.add_parser("review", help="run the ADS-055 review corpus and print or write the report")
    review.add_argument("--write-report", metavar="DIR")
    evaluation = sub.add_parser(
        "evaluation", help="run the ADS-056 candidate evaluation corpus and print or write the report"
    )
    evaluation.add_argument("--write-report", metavar="DIR")
    rollout = sub.add_parser("rollout", help="run the ADS-057 rollout corpus and print or write the report")
    rollout.add_argument("--write-report", metavar="DIR")
    drift = sub.add_parser("drift", help="run the ADS-058 drift corpus and print or write the report")
    drift.add_argument("--write-report", metavar="DIR")
    poisoning = sub.add_parser("poisoning", help="run the ADS-059 poisoning corpus and print or write the report")
    poisoning.add_argument("--write-report", metavar="DIR")
    security = sub.add_parser("security", help="run the ADS-067 security corpus and print or write the report")
    security.add_argument("--write-report", metavar="DIR")
    resilience = sub.add_parser("resilience", help="run the ADS-068 restore and failover drills and print or write the report")
    resilience.add_argument("--write-report", metavar="DIR")
    resilience.add_argument("--write-fixtures", action="store_true", help="regenerate the pinned checkpoint fixtures (a compatibility decision)")
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

    if args.command == "resilience":
        import tempfile
        from pathlib import Path

        from reference_stack import resilience_eval

        if args.write_fixtures:
            print(json.dumps(resilience_eval.write_checkpoint_fixtures(), indent=2))
            return 0
        objectives = resilience_eval.load_objectives()
        root = Path(tempfile.mkdtemp(prefix="analytics-resilience-"))
        drills = {
            "restore": resilience_eval.drill_restore(root / "restore", objectives),
            "failover": resilience_eval.drill_failover(root / "failover", objectives),
        }
        markdown = resilience_eval.render_markdown(drills, objectives)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-068-resilience-report.md").write_text(markdown)
            payload = {name: {"result": d["result"].model_dump(), "measured": d["measured"]} for name, d in drills.items()}
            (target / "ADS-068-resilience-report.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
        else:
            print(markdown)
        passed = all(d["result"].passed for d in drills.values())
        print(f"drills passed: {passed}")
        return 0 if passed else 1

    if args.command == "security":
        import tempfile
        from pathlib import Path

        from reference_stack.security_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-security-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-067-security-report.md").write_text(markdown)
            (target / "ADS-067-security-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    if args.command == "poisoning":
        import tempfile
        from pathlib import Path

        from reference_stack.poisoning_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-poisoning-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-059-poisoning-report.md").write_text(markdown)
            (target / "ADS-059-poisoning-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    if args.command == "drift":
        import tempfile
        from pathlib import Path

        from reference_stack.drift_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-drift-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-058-drift-report.md").write_text(markdown)
            (target / "ADS-058-drift-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    if args.command == "rollout":
        import tempfile
        from pathlib import Path

        from reference_stack.rollout_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-rollout-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-057-rollout-report.md").write_text(markdown)
            (target / "ADS-057-rollout-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    if args.command == "evaluation":
        import tempfile
        from pathlib import Path

        from reference_stack.evaluation_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-evaluation-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-056-evaluation-report.md").write_text(markdown)
            (target / "ADS-056-evaluation-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    if args.command == "review":
        import tempfile
        from pathlib import Path

        from reference_stack.review_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-review-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-055-review-report.md").write_text(markdown)
            (target / "ADS-055-review-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    if args.command == "prompts":
        import tempfile
        from pathlib import Path

        from reference_stack.prompt_registry_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-prompts-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-054-prompt-registry-report.md").write_text(markdown)
            (target / "ADS-054-prompt-registry-report.json").write_text(
                json.dumps(report, indent=2, default=str) + "\n"
            )
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    if args.command == "dbt":
        import tempfile
        from pathlib import Path

        from reference_stack.dbt_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-dbt-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-053-dbt-proposals-report.md").write_text(markdown)
            (target / "ADS-053-dbt-proposals-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

    if args.command == "proposals":
        import tempfile
        from pathlib import Path

        from reference_stack.proposal_eval import render_markdown, run_corpus

        report = run_corpus(Path(tempfile.mkdtemp(prefix="analytics-proposals-")))
        markdown = render_markdown(report)
        if args.write_report:
            target = Path(args.write_report)
            target.mkdir(parents=True, exist_ok=True)
            (target / "ADS-052-proposals-report.md").write_text(markdown)
            (target / "ADS-052-proposals-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        else:
            print(markdown)
        failed = [c for c in report["cases"] if not c["passed"]]
        print(
            f"cases: {len(report['cases']) - len(failed)}/{len(report['cases'])} passed; meets thresholds: {report['meets_thresholds']}"
        )
        return 0 if report["meets_thresholds"] else 1

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
