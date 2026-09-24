# ADS-025: Fault-Injection DSL

Status: **Complete**
Milestone: M2
Depends on: ADS-023

## Deliverable

`services/analytics-api/app/harness/faults.py` provides a small deterministic
fault plan DSL for stale context, timeout, policy denial, node crash, and
malformed model output. A plan wraps local handlers and returns redacted typed
failures at the selected node without network access or process-level chaos.

The graph harness maps those failures to bounded terminal outcomes:
`stale_context` becomes `review_required`, `policy_denied` becomes `refused`,
and timeout, crash, or malformed model output becomes `failed`. Failure and
cancellation terminalization is legal from every registered node; normal
successful edges remain allowlisted.

## Evidence

- `services/analytics-api/app/harness/faults.py`
- `packages/platform_contracts/agent_runtime.py`
- `services/analytics-api/tests/test_ads025_faults.py`
- Each required fault reaches its declared terminal outcome and duplicate fault
  registration is rejected.

## Boundary

The DSL models bounded fault outcomes for deterministic evaluation. It does
not claim to kill processes, simulate network partitions, or replace staging
operations drills.
