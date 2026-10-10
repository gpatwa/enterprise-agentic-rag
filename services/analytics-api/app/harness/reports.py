"""Stable JSON, JUnit, and Markdown renderers for grader reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from app.harness.graders import LayeredGradeReport


def render_json(report: LayeredGradeReport, *, baseline: Any | None = None) -> str:
    payload: dict[str, Any] = {"report": report.model_dump(mode="json")}
    if baseline is not None:
        payload["baseline"] = baseline.model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_junit(report: LayeredGradeReport) -> str:
    failures = sum(not finding.passed for finding in report.findings)
    suite = Element(
        "testsuite",
        name=f"agentic-data-stack:{report.suite_version}",
        tests=str(len(report.findings)),
        failures=str(failures),
    )
    for finding in report.findings:
        case = SubElement(suite, "testcase", classname=report.case_id, name=finding.stage)
        if not finding.passed:
            failure = SubElement(case, "failure", message="; ".join(finding.reasons))
            failure.text = "; ".join(finding.reasons)
    return tostring(suite, encoding="unicode") + "\n"


def render_markdown(report: LayeredGradeReport, *, baseline: Any | None = None) -> str:
    lines = [
        f"# Agentic Evaluation: `{report.case_id}`",
        "",
        f"- Suite: `{report.suite_version}`",
        f"- Report version: `{report.report_version}`",
        f"- Overall: **{'PASS' if report.passed else 'FAIL'}**",
        "",
        "| Stage | Status | Score | Findings |",
        "| --- | --- | ---: | --- |",
    ]
    for finding in report.findings:
        reasons = "; ".join(finding.reasons) or "-"
        lines.append(f"| `{finding.stage}` | {'PASS' if finding.passed else 'FAIL'} | {finding.score:.3f} | {reasons} |")
    if baseline is not None and getattr(baseline, "regressions", ()):
        lines.extend(["", "## Regressions", "", *[f"- {item}" for item in baseline.regressions]])
    return "\n".join(lines) + "\n"


def write_report_artifacts(report: LayeredGradeReport, directory: str | Path, *, baseline: Any | None = None) -> dict[str, Path]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": target / "agentic-evaluation.json",
        "junit": target / "agentic-evaluation.xml",
        "markdown": target / "agentic-evaluation.md",
    }
    paths["json"].write_text(render_json(report, baseline=baseline))
    paths["junit"].write_text(render_junit(report))
    paths["markdown"].write_text(render_markdown(report, baseline=baseline))
    return paths
