# ADS-020: Scenario and Expected-Trace Schema

Status: **Complete**
Milestone: M2
Depends on: ADS-003

## Deliverable

`packages/platform_contracts/harness.py` defines the versioned `HarnessScenario`,
`ExpectedTrace`, `ExpectedTraceStep`, and `HarnessReport` contracts. Fixtures
are content-addressed, tenant- and context-scoped, require a matching graph
version, and reject illegal, disconnected, non-contiguous, or non-terminal
expected traces with actionable validation errors.

## Evidence

- `packages/platform_contracts/harness.py`
- `services/analytics-api/tests/test_harness_m2.py`
- Round-trip, digest, transition, and trace-shape tests pass.

## Boundary

This packet describes expected behavior. It does not run a graph or authorize
tools; graph execution begins in ADS-023.
