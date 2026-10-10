# ADS-030: Governed Graph Runner

Status: **Complete**
Milestone: M3
Depends on: ADS-009, ADS-023

## Deliverable

`services/analytics-api/app/runtime/graph_runner.py` executes a versioned,
registered graph against the durable analytics control store. It validates
graph versions and allowlisted destinations, checks deadlines and transition
and cost budgets before continuing, detects a repeated state fingerprint,
normalizes node errors, and terminalizes cancellation or failure with typed
evidence.

Every accepted step is committed through the existing compare-and-set and
lease-fencing boundary in `ControlStore`. `start` creates and leases a run;
`resume` acquires a fresh lease and continues from the latest committed
checkpoint. The control store now exposes tenant/purpose-scoped run loading,
durable cancellation requests, and cancellation polling for the runner.

## Evidence

- `services/analytics-api/app/runtime/graph_runner.py`
- `services/analytics-api/app/runtime/control_store.py`
- Existing M0 fencing, tenant-scope, transition-log, and checkpoint integration
  coverage exercises the persistence boundary.
- ADS-030 static validation: Ruff and `git diff --check` pass.

## Boundary

The runner invokes only registered local handlers. It does not wire the public
API, live model, warehouse, or human approval path. M1 semantic certification
and live OpenSearch validation remain separate gates.
