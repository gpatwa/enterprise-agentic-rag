# ADS-069: Operations Dashboard and Runbooks for Every Release Gate

Status: **Review** (implemented and locally verified; local fakes only; **not** an operations readiness review)
Milestone: M6 (wave 6C)
Depends on: ADS-058, ADS-065, ADS-066, ADS-067, ADS-068

## Decisions made under the user's delegation ("make the decision")

1. **A read-only library and report, not a mounted UI.** `build_dashboard` aggregates tenant usage, quota and SLO alerts, drift alerts, release-gate rows, and open security
   finding ids into a frozen `Dashboard`. Nothing starts, stops, or changes anything.
2. **Gate rows echo evidence; they never grant approval.** Status is `passing` (thresholds met and `approved` in the file), `unapproved` (met, but a person has not approved),
   `failing`, or `missing`. Only `failing` pages. The dashboard cannot write an approval.
3. **Every alert and gate resolves to a runbook.** 11 `ops-*` runbooks (plus the six ADS-058 `drift-*`), each with the required sections; a test checks every runbook id used in code.
4. **Diagnosis reads durable records only.** `diagnose_run` reports status, terminal kind, node path, whether the transition history is contiguous, and evidence ids (with the
   run ID replaced by `run_ref`). It carries no question text, SQL, rows, or tokens. A gap in the history is reported, not hidden.
5. **Replay = determinism.** Each seeded failure is built twice from scratch; the signatures must match. Re-submitting a request with the same idempotency key returns the same run.

## Deliverable

- `packages/platform_contracts/ops_dashboard.py`, `app/operations/dashboard.py`, `reference_stack/operations_eval.py`, `make analytics-operations-drill`
- Runbooks: `ops-cost-budget`, `ops-rate-limit`, `ops-slo-burn`, `ops-slo-latency`, `ops-run-diagnosis`, `ops-release-gate`, `ops-security-finding`, `ops-restore`, `ops-failover`,
  `ops-deployment-checklist` (run_id_key, min_cohort, shared quota state, verified backup), `ops-rolling-upgrade`
- Seeded failures: cost budget exhausted, rate limited, SLO fast burn, SLO latency, policy-refused run, corrupt backup, failing security gate
- Report: `reports/ADS-069-operations-report.{md,json}`; tests: `tests/test_ads069_operations.py`

## Evidence

Full analytics suite: 828 passed. Drill: all seven scenarios diagnosed and replayed identically; runbook problems: none.

## Boundary

- The dashboard is not mounted or served and has no live data source; production metrics, paging, and ticketing are not wired.
- Quota state is process-local; the failover and restore scenarios run on local SQLite/DuckDB.
- The operations review (M6 gate `security_and_operations_review`) and independent review are the user's; nothing here records them.
