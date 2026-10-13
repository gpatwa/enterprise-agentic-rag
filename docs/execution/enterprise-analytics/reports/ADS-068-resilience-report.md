# ADS-068: Resilience Drill Report

Generated 2026-10-13 16:30 UTC by `make analytics-resilience-drill`. Objectives `resilience-objectives-v1` (**proposed**): RPO 900s, RTO 900s, lease 30s.

The objectives are **PROPOSED and NOT APPROVED**. This is not the M6 `security_and_operations_review`. The drills run on the reference stack with SQLite, DuckDB, and fakes: they measure the mechanisms, not production recovery.

Restore seconds are wall-clock time on this machine; failover seconds are **simulated** (a fake clock advanced past the lease expiry), not elapsed time.

| Drill | Passed | Seconds | Findings |
|---|:---:|---:|---|
| restore | yes | 0.107 | - |
| failover | yes | 31.000 | - |

## Measurements

**restore**
- `backup_seconds`: 0.06227
- `restore_seconds`: 0.1072
- `data_loss_window_seconds`: 600
- `runs_in_backup`: 5
- `runs_lost`: 3
- `rows_backed_up`: 199
- `evidence_envelopes_verified`: 2
- `feedback_restored`: True
- `answer_rows_survive_restart`: False

**failover**
- `takeover_seconds`: 31
- `lease_seconds`: 30
- `query_executions`: 1
- `fencing_seq_after_takeover`: 2
- `transitions`: 13

## What a restore does not bring back

- Answer rows and explanations live in process-local stores, so a restored or restarted API cannot re-serve an old answer's rows: the evidence and fingerprints survive, the user re-asks. Compiled plans and policy values are also process-local, so a run paused for review before a restart fails closed on resume instead of executing.
- Run leases are not restored; workers take new ones.
