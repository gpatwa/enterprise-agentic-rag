# ADS-023: Graph Execution Harness

Status: **Complete**
Milestone: M2
Depends on: ADS-020, ADS-021, ADS-022

## Deliverable

`services/analytics-api/app/harness/graph.py` provides a deterministic,
network-free graph harness for the authored `graph-v1` lifecycle. It executes
registered node handlers through the typed `NodeInput` and `NodeOutput`
contracts, emits versioned `Transition` facts, creates an evidence-backed
terminal outcome, and returns the final run state and payload.

The harness fails closed on unregistered nodes, malformed output identity,
illegal edges, repeated nodes, unsupported waiting outputs, transition-budget
exhaustion, and handler exceptions. It compares the observed trace against the
scenario's expected trace and reports missing, extra, or mismatched transitions
separately.

`terminal` is an internal success sentinel for a node output. The recorded
transition remains the contractually correct `to_node=None, to_status=terminal`
shape.

## Evidence

- `services/analytics-api/app/harness/graph.py`
- `services/analytics-api/tests/test_ads023_graph_harness.py`
- Happy-path, missing-transition, extra-transition, cycle, illegal-edge,
  terminal-outcome, and budget assertions pass without network access.

## Boundary

This packet is a test harness, not the production graph runner. It does not
persist checkpoints, acquire leases, invoke live models or tools, or authorize
external actions. Those concerns remain gated by later packets and by the M1
semantic-certification and live OpenSearch validation gates.
