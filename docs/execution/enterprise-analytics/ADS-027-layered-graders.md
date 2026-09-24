# ADS-027: Layered Deterministic Graders

Status: **Complete**
Milestone: M2
Depends on: ADS-023

## Deliverable

`services/analytics-api/app/harness/graders.py` grades retrieval, intent, AST,
result, policy, trace, and evidence independently. Each stage emits a score
and actionable reasons; deterministic security, policy, trace, and evidence
findings are not overridden by an LLM judge.

## Evidence

- `services/analytics-api/app/harness/graders.py`
- `services/analytics-api/tests/test_ads027_graders.py`
- Deliberate defects fail only their responsible grader.

## Boundary

The grader consumes normalized observations. It does not retrieve live data,
execute SQL, or decide customer-specific release thresholds.
