# ADS-068: Backup, Restore, HA, Rolling Upgrade, and Checkpoint Compatibility

Status: **Review** (implemented and locally verified; local drills only; **not** a production recovery test)
Milestone: M6 (wave 6C)
Depends on: ADS-005, ADS-065

## Decisions made under the user's delegation ("make the decision")

1. **Logical backup, in SQL.** A backup is a directory of per-table JSON-lines files plus a manifest (schema revision, per-table row counts and digests,
   an overall digest). It uses only SQL and the table dependency order, so the same code serves SQLite here and PostgreSQL in the target. Native
   `pg_dump`/PITR is the production tool; this is the portable, verifiable mechanism and the basis for drills.
2. **Restore is verified, not trusted.** It refuses a corrupt, tampered, or incomplete backup, a different schema revision, or a non-empty target
   *before writing*; it writes in one transaction; then it re-derives counts and digests and re-verifies **every tenant's evidence chain**, so an operator
   who also re-signs the manifest still cannot forge the chain.
3. **Leases are not backed up.** A restored worker must take new leases (fencing numbers restart safely under the restored state).
4. **HA is lease takeover plus fencing.** A dead worker's run is resumed by another worker only after its lease expires; a worker that wakes up later and
   tries to continue is rejected (a stale fencing number).
5. **Rolling-upgrade rule: expand, then contract.** A new field on persisted state must be optional with a default and must not be written until every
   worker can read it, because an older reader rejects unknown fields (by design: it refuses rather than misreads). Pinned checkpoint fixtures are the
   compatibility contract between releases.
6. **The objectives are proposed** (RPO 15 min, RTO 15 min, lease 30 s, takeover within twice the lease). They were chosen without production data.

## Deliverable

- `packages/platform_contracts/resilience.py`: `ControlBackupManifest`, `ResilienceObjectives` (with an approval block).
- `app/resilience/backup.py`: `backup_control_store`, `verify_backup_files`, `restore_control_store`, `ResilienceError` (stable codes:
  `backup_corrupt`, `backup_table_missing`, `backup_manifest_unreadable`, `backup_manifest_tampered`, `schema_revision_mismatch`,
  `schema_tables_mismatch`, `target_not_empty`, `restore_verification_failed`, `restored_evidence_chain_broken`, `backup_destination_exists`).
- `reference_stack/resilience_eval.py`: the **restore drill** (back up, keep writing, lose the database, restore into a fresh one, measure recovery time and
  loss against the objectives) and the **failover drill** (a worker crashes after the execute checkpoint; a second worker is refused until the lease expires,
  then finishes the run; the query runs exactly once; a zombie worker is fenced), plus the pinned checkpoint fixtures
  (`tests/fixtures/checkpoints/`, a lock file, and `--write-fixtures` to regenerate them as an explicit compatibility decision).
- `services/analytics-api/resilience/objectives.proposed.json` (**proposed**); `make analytics-resilience-drill` writes `reports/ADS-068-resilience-report.md`.
- **Two real defects fixed along the way:** after a restart or restore, asking for a previously answered run raised an unhandled `LookupError` (a 500);
  the service now reports the documented "answer unavailable" outcome, and the reference answer source returns `None` instead of raising.

## Evidence

- `tests/test_ads068_resilience.py` (20 tests): objectives valid and proposed; a backup holds every durable table but not leases and restores
  **byte-for-byte** (a second backup of the restored database has the same digest); a restored database accepts new work; five kinds of damage are refused
  before anything is written; a non-empty target, an older schema, and an existing backup directory are refused; **a failure part-way through a restore
  leaves the target empty**; a forged evidence chain is rejected even with a re-signed manifest; the restore drill meets the objectives and reports exactly
  what was lost (the 3 runs written after the backup), and flags an RPO overrun and an RTO overrun; a restored service says an old answer's rows are
  unavailable and **never executes a run that was paused for review before the restart**; the failover drill takes over after the lease, runs the query
  once, advances the fencing number, fences the zombie, and flags a too-slow takeover; the four pinned fixtures are unchanged, load, round-trip
  byte-for-byte, and store/read back through the control store; an older writer's state loads and a newer writer's unknown field or schema version is
  refused; a database upgraded with data in it keeps the data across upgrade, downgrade, and upgrade; and a run started by one worker build is finished by
  another while an unknown graph version is refused.
- `make analytics-resilience-drill`: both drills pass (restore 0.03 s wall-clock; failover takeover at 31 simulated seconds).

## What a restore does not bring back (decisions for the owners)

- **Answer rows and explanations** live in process-local stores. After a restart or restore the evidence and fingerprints survive, but a past answer's
  rows do not: the user re-asks. Durable result storage would also mean durable (and access-controlled) copies of sensitive rows; that is a design decision, not
  a bug fix.
- **Compiled plans, policy values, and results are process-local**, so a run paused for review across a restart **fails closed** on the decision instead of
  executing. Safe, but the requester must re-ask; surviving restarts needs durable plan storage (and a decision about holding policy values at rest).
- **Quota and rate state** is in memory and per replica (ADS-066).

## Boundary

- Local drills on SQLite and DuckDB with fakes: they prove the mechanisms and measure them at toy scale (hundreds of rows). Real RPO and RTO need the
  production database, its size, its backup tooling (PITR, replication), and a staging drill, which needs your authorization and environment.
- No real high availability was exercised: no multiple processes or hosts, no network partitions, no database failover. Failover seconds in the report are simulated.
- PostgreSQL was not used; the backup code is dialect-neutral SQL but untested against a server, and an inconsistent multi-table snapshot under concurrent writes
  (PostgreSQL needs `REPEATABLE READ`) is not handled.
- Rolling upgrade across two *code versions* was simulated with differently built handler sets and pinned fixtures, not two real releases.

## Update (M7-H1)

Compiled plans and policy values are now stored durably (`analytics_run_plans`, `analytics_run_policy_values`, `analytics_run_result_links`; migration `0012_durable_run_material`), and these tables are part of the logical backup. A run paused for review therefore survives a restart or restore: the reviewer's decision decides it and an approval runs the stored plan once. Result rows are still never stored, so a status read of an old answered run still says the answer is unavailable (and never runs a query). The earlier statement above that a paused review fails closed after a restart no longer holds.
