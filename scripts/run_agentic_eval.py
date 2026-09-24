"""Generate the committed local evaluation artifacts for CI."""
from __future__ import annotations

from pathlib import Path

from app.harness import BaselineLock, GradeCase, grade_case, render_json, render_junit, render_markdown

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "services/analytics-api/tests/fixtures/ads-m2-baseline.json"
OUTPUT = ROOT / "artifacts/agentic-evaluation"


def main() -> int:
    baseline = BaselineLock.model_validate_json(BASELINE.read_text())
    report = grade_case(GradeCase(case_id="ads-m2-ci-smoke", suite_version=baseline.suite_version, trace_valid=True))
    comparison = baseline.compare(report)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "agentic-evaluation.json").write_text(render_json(report, baseline=comparison))
    (OUTPUT / "agentic-evaluation.xml").write_text(render_junit(report))
    (OUTPUT / "agentic-evaluation.md").write_text(render_markdown(report, baseline=comparison))
    return 1 if comparison.blocked or not report.passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
