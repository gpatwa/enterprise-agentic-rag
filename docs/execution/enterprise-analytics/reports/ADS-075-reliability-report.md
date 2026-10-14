# ADS-075: Reliability, Crash/Replay, Dependency-Failure, and Chaos Evaluation

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. Local fakes only: this measures mechanisms, not production availability.

26 crash points x 2 models, 7 dependency faults, 40 seeded chaos runs (seed 20261013; mix {'dependency': 18, 'crash': 17, 'none': 5}).

## Metrics

| Metric | Measured | Gate | Meets | Plan gate |
|---|---:|---:|:---:|---|
| `wrong_answers` | 0 | <= 0 | yes | Answers whose rows differ from the independent oracle: 0 |
| `duplicate_executions` | 0 | <= 0 | yes | A query executed more than once for one run, other than after a process crash: 0 |
| `reexecution_outside_window` | 0 | <= 0 | yes | After a process crash, a query run again although the rows had not been produced yet: 0 |
| `max_executions_per_run` | 2 | <= 2 | yes | Executions per run never exceed the one original plus one rebuild after a process crash |
| `unhandled_errors` | 0 | <= 0 | yes | Errors that reach the caller untyped (a raw exception or HTTP 500): 0 |
| `unsafe_outcomes` | 0 | <= 0 | yes | Runs that end in neither a correct answer nor a typed failure: 0 |
| `evidence_chain_breaks` | 0 | <= 0 | yes | Evidence chains that no longer verify: 0 |
| `crash_recovery_same_process` | 1 | >= 1.0 | yes | Worker-crash points that still end in a correct answer (stores intact) |
| `crash_recovery_process_death` | 1 | >= 1.0 | yes | Process-crash points (fresh process, same database) that still end in a correct answer |
| `crash_safe_ending_process_death` | 1 | >= 1.0 | yes | Process-crash points that end safely: a correct answer or a typed failure |
| `dependency_failures_handled` | 1 | >= 1.0 | yes | Dependency failures that end in a typed failure or a degraded-but-correct answer |
| `chaos_safe_ending_rate` | 1 | >= 1.0 | yes | Chaos runs that end safely |

## A real process crash

With fresh in-memory stores on the same database, 26 of 26 crash points finish with a correct answer. Compiled plans and policy values are stored durably (M7-H1) so another process can continue the run; result rows are never stored, and a result missing after a crash is rebuilt by running the stored plan again while the run is in flight.

## Dependency failures

| Fault | Verdict | Outcome | Code | Queries run |
|---|---|---|---|---:|
| warehouse_down | typed_failure | failed | executor_unavailable | 1 |
| estimator_down | typed_failure | failed | executor_unavailable | 0 |
| context_search_down | typed_failure | refuse | stale_metadata | 0 |
| context_snapshot_down | typed_failure | service_error | context_unavailable | 0 |
| explainer_down | correct_answer (degraded) | answer | None | 1 |
| model_timeout | typed_failure | failed | planner_unavailable | 0 |
| deadline_already_passed | typed_failure | failed | query_timeout | 0 |

## Not measured

- **availability_percentage**: no availability target has been declared and no uptime was measured; these are mechanism tests
- **real_process_recovery**: the process crash is simulated by a second stack object on the same database; a real process crash in a deployed environment (separate hosts, a real PostgreSQL, lease expiry on wall-clock time) is not exercised. Result rows are rebuilt by running the stored plan again, so a rebuilt answer reflects the data at rebuild time.
- **retry_after_failure**: a failed run is terminal and the same idempotency key returns the same failure; a client must use a new key to retry. No retry guidance beyond the `retryable` flag exists.
- **real_dependencies**: the warehouse, search, model, and explainer failures are simulated exceptions; timeouts, partial responses, slow dependencies, and network partitions are not modelled
- **concurrency**: crashes are injected one at a time; concurrent crashes and contention are covered only by the ADS-066 load simulator and the ADS-068 failover drill
- **at_least_once_reads**: after a process crash that follows the query, the stored plan runs again once to rebuild the rows (reads are idempotent but cost twice); exactly-once execution across processes would need result rows to be stored, which was not chosen.
