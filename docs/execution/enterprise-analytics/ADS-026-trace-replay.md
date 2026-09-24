# ADS-026: Trace Capture, Redaction, Export, and Replay

Status: **Complete**
Milestone: M2
Depends on: ADS-023

## Deliverable

`services/analytics-api/app/harness/trace.py` captures versioned transition
traces without storing raw prompts, credentials, or unbounded payloads. Captured
traces are content-addressed, JSON exportable, loadable, and replayable against
the local fake-backed graph with no model, network, or warehouse dependency.

## Evidence

- `services/analytics-api/app/harness/trace.py`
- `services/analytics-api/tests/test_ads026_trace_replay.py`
- Redaction, export/load, digest validation, fixture identity, and deterministic
  replay tests pass.

## Boundary

Replay proves the local graph trace contract. It is not a production audit-log
store and does not replace the later durable evidence boundary.
