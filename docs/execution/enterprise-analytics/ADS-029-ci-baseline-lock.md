# ADS-029: CI Matrix and Baseline Lock

Status: **Complete**
Milestone: M2
Depends on: ADS-024, ADS-025, ADS-026, ADS-027, ADS-028

## Deliverable

`services/analytics-api/app/harness/baseline.py` compares stage scores to the
committed baseline lock at
`services/analytics-api/tests/fixtures/ads-m2-baseline.json`. Changing the
fixture digest, suite version, or any threshold requires an independent,
identity-bound approval with rationale. Lowering a gate silently is rejected.

`.github/workflows/ci-agentic-eval.yml` runs the platform contracts, harness,
and grader/report slices as a CI matrix and publishes the JSON, JUnit, and
Markdown artifacts.

## Evidence

- `services/analytics-api/app/harness/baseline.py`
- `services/analytics-api/tests/test_ads029_baseline.py`
- `services/analytics-api/tests/fixtures/ads-m2-baseline.json`
- `.github/workflows/ci-agentic-eval.yml`
- Regression detection and approval-required tests pass.

## Boundary

The baseline is a local evaluation lock, not a production customer threshold.
The M2 threshold-and-harness review was approved by the user on 2026-09-24;
the approved record is in `agentic-data-stack-program.yaml`. Threshold changes
still require independent approval.
