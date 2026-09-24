# ADS-024: Node Contract Kit

Status: **Complete**
Milestone: M2
Depends on: ADS-023

## Deliverable

`services/analytics-api/app/harness/node_contracts.py` provides the shared node
boundary for local graph execution. It validates run and node identity,
normalizes typed errors and timeouts into redacted `NodeOutput` failures, and
converts a cancellation request into a terminal-safe cancelled output before a
handler runs.

`NodeContractKit.conformance(...)` invokes every registered node's success path
and verifies the common typed-error, timeout, and cancellation shapes. A
`NodeConformanceReport` identifies the exact node and contract case that failed.

## Evidence

- `services/analytics-api/app/harness/node_contracts.py`
- `services/analytics-api/tests/test_ads024_node_contracts.py`
- Every graph fixture node passes the conformance suite; invalid identity,
  typed error, timeout, and cancellation cases are rejected or normalized.

## Boundary

This kit does not retry nodes, persist attempts, or decide policy. It supplies
the typed boundary used by the local harness; durable retry and production
execution remain later runtime work.
