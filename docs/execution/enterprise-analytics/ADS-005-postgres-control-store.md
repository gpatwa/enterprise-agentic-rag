# ADS-005: PostgreSQL Control Store

Status: **Review**
Depends on: ADS-003

## Delivered

- Added analytics migration `0002_agent_control_store` for tenant-scoped agent
  runs, immutable checkpoint history, fenced leases, append-only transition
  facts, and a delivery-state outbox.
- Added database constraints for status domains, non-negative sequence and
  attempt values, foreign-key ownership, unique transition idempotency, and
  outbox deduplication.
- Added SQLite append-only triggers and the equivalent PostgreSQL trigger
  function for transition facts. A transition is keyed by `(run_id,
  transition_seq)` so a resume cannot insert a second fact for the same step.
- Checkpoints retain graph/state versions, serialized state, node position,
  transition sequence, tenant, and fencing sequence needed to resume from the
  last committed boundary.

## Verification

```text
PYTHONPATH=. pytest -q services/analytics-api/tests/test_ads005_control_store_migration.py
PYTHONPATH=. pytest -q services/analytics-api/tests/test_persistence_migrations.py
ruff check services/analytics-api/tests/test_ads005_control_store_migration.py
ruff format --check services/analytics-api/tests/test_ads005_control_store_migration.py
git diff --check
```

The migration test covers schema discovery and downgrade, crash/resume
checkpoint uniqueness, stale fencing sequence rejection, monotonic transition
ordering, append-only mutation rejection, and duplicate outbox delivery
deduplication.

## Scope and non-goals

This packet defines the durable schema only. It does not add the graph runner,
compare-and-set repository methods, lease acquisition SQL, routing flags,
outbox worker, cloud deployment, or manifest status changes. Application code
must perform conditional updates using the fencing sequence and must claim
outbox rows with a transaction appropriate to the deployed PostgreSQL version.

## Residual risks

- The local tests use SQLite; PostgreSQL-specific locking, isolation, and
  `SKIP LOCKED` claim behavior still require a live integration drill.
- The database cannot infer whether a transition's fencing sequence is the
  current lease without repository-side compare-and-set logic; ADS-005 stores
  the facts and supplies the constraints for that implementation.
- Tenant authorization remains an application/RLS deployment concern and is
  not enabled by this migration because the repository has no shared RLS
  convention yet.
