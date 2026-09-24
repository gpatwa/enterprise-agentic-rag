# ADS-028: Evaluation Report Renderers

Status: **Complete**
Milestone: M2
Depends on: ADS-027

## Deliverable

`services/analytics-api/app/harness/reports.py` renders the layered report as
stable JSON, JUnit XML, and concise Markdown. Each artifact carries the case,
suite/report version, stage status, score, and finding reasons so CI and a
human reviewer can identify the failing contract quickly.

## Evidence

- `services/analytics-api/app/harness/reports.py`
- `services/analytics-api/tests/test_ads028_reports.py`
- Renderer and artifact-writing tests pass.

## Boundary

Renderers do not change grades or thresholds; they only serialize the result.
