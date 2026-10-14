# ADS-075: Reliability, Crash/Replay, Dependency-Failure, and Chaos Evaluation

Status: **Review** (local mechanism tests; thresholds **proposed, not approved**; **not an availability measurement**)
Milestone: M7 (wave 7B)
Depends on: ADS-068

## Decisions made under the user's delegation ("make the decision")

1. **Two crash models, because only one is honest.** A worker crash is injected before and after each of the 13 nodes of a normal run (26 points). Run once with the process's in-memory stores intact (a
   worker thread died) and once with fresh stores on the same database (the process died; compiled plans, policy values, and result rows are process-local).
2. **Seven dependency faults** (warehouse, cost estimator, context search, context snapshot, explainer, model, an already-passed deadline) and a **seeded chaos mix** (40 runs, seed 20261013) judged on the
   same invariants: a correct answer or a typed failure; rows equal to the independent oracle; at most one execution per run; no untyped error; the evidence chain verifies.
3. **No availability percentage is claimed.** The plan says "declared availability", but none is declared; the gates are the invariants above plus "a worker crash always still ends in a correct answer".

## Defects the evaluation found, and what was done

| Finding | Action |
|---|---|
| A crash after the query ran but before the step committed ran the query a **second time** on resume (at-least-once execution). | Fixed: the executor keeps and reuses the earlier worker's result (`ExecutionResultStore.reference_for/has`). |
| A crash after compiling made the resumed run **fail permanently**: policy values were consumed on first read. | Fixed: `PolicyValueStore.get` no longer consumes (bounded, oldest-first eviction, `discard` added). The compiled-plan store already holds the same values as parameters, so retention is unchanged. |
| A dead context provider at run start raised an **unhandled error** (HTTP 500). | Fixed: reported as `503 context_unavailable`. |
| A warehouse or estimator outage was reported as a non-retryable `internal_error`. | Fixed: reported as `executor_unavailable` (retryable). |
| **A real process crash after the compile step cannot be continued** (10 of 26 crash points fail closed with `internal_error`; none returns a wrong answer). | **Open**: needs durable compiled-plan and result storage (or re-planning on resume). Decision for the user. |
| A failed run is terminal and the same idempotency key returns the same failure, so a client must use a new key to retry. | **Open**: no retry guidance exists beyond the `retryable` flag. |

## Deliverable

- `reference_stack/reliability_eval.py`, `m7/reliability-thresholds.proposed.json`, `make analytics-m7-reliability`, report `reports/ADS-075-reliability-report.{md,json}`, `tests/test_ads075_reliability.py`
- Fixes: `app/execution/bridge.py`, `app/runtime/governed_stages.py`, `app/runtime/analyze_service.py`

## Boundary

- Failures are simulated exceptions, one at a time; slow dependencies, partial responses, partitions, and concurrent crashes are not modelled. Thresholds are the user's to approve.
