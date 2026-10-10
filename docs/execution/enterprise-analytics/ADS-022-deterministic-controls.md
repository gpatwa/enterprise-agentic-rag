# ADS-022: Deterministic Run Controls

Status: **Complete**
Milestone: M2
Depends on: ADS-020

## Deliverable

`packages/platform_contracts/determinism.py` provides deterministic clock, ID,
randomness, token, and cost controls. The local harness probe in
`services/analytics-api/app/harness/replay.py` uses those controls to produce
repeatable semantic reports and fails closed when token or cost budgets are
exceeded.

## Evidence

- `packages/platform_contracts/determinism.py`
- `services/analytics-api/app/harness/replay.py`
- `services/analytics-api/tests/test_harness_m2.py`
- Same seed and scenario produce an identical report; changed seed changes the
  semantic fingerprint; budget overflow is rejected.

## Boundary

This is the deterministic substrate for the graph harness. It does not claim
that a live model, warehouse, or agent graph has been evaluated yet.
