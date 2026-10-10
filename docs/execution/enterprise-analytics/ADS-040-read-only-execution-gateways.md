# ADS-040: PostgreSQL and DuckDB Read-Only Execution Gateways

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M4
Depends on: ADS-037

## Deliverable

`services/analytics-api/app/execution/` adds the first real execution boundary
behind the graph's executor and estimator slots.

- `CompiledQuery` now carries a `dialect`; `DuckDBCompilerAdapter` joins the
  PostgreSQL adapter. A gateway refuses a plan compiled for another dialect.
- `validate_read_only_sql` is a caller-allowlisted, dialect-aware AST guard:
  one read-only statement, no DDL/DML/COPY/ATTACH/SET, no table-valued
  functions, an explicit function allowlist, and table names only from the
  gateway's allowlist.
- `DuckDBGateway` builds a fresh in-memory database per execution exposing only
  registered Parquet/CSV files that resolve inside an allowed root, then sets
  `allowed_paths`, disables external access, and locks configuration, so even
  SQL that bypassed validation cannot read other files, write, attach, or
  re-enable access. Timeout and cancellation use the engine's interrupt.
- `PostgresGateway` takes an injected SQLAlchemy engine and runs the query in
  `SET TRANSACTION READ ONLY` with `statement_timeout`/`lock_timeout`, checks the
  planner's `EXPLAIN` total cost against the limit before running, streams rows
  under row and byte caps, cancels through the driver's `cancel()`, and always
  rolls back.
- `ExecutionLimits` bounds timeout, rows, bytes, and cost. Row/byte overflow is
  reported as `truncated` with a reason (ADS-041 consumes this); cost,
  timeout, cancellation, rejection, and dialect mismatch raise typed errors that
  never echo SQL or parameter values.
- `GatewayExecutor`, `GatewayCostEstimator`, and `ExecutionResultStore` plug the
  gateways into the existing `fake_execution_node` / `estimate_node` contracts.

## Evidence

- `services/analytics-api/tests/test_ads040_execution_gateways.py` (37 tests):
  DuckDB result equals an independent aggregation of the same Parquet file;
  unsafe-SQL matrix; engine-level isolation test against a locked connection;
  row, byte, cost, timeout, cancellation (mid-run and pre-cancelled); PostgreSQL
  behavior against a recording fake engine; graph node through the bridge.

## Boundary

- DuckDB runs against real embedded DuckDB. **PostgreSQL has not been exercised
  against a live server**: its tests use a fake engine and verify the statements
  issued, not server behavior. A live-PostgreSQL validation (including real
  cancellation and EXPLAIN output shape on the pinned server version) is a
  separate gate requiring explicit authorization.
- Cost units are per dialect (DuckDB: summed planner cardinalities; PostgreSQL:
  planner total cost). Run budgets compare against them as-is until a
  calibration packet normalizes them.
- Roles/credentials, durable result storage, and result validation belong to
  deployment, ADS-042, and ADS-041. The result store is process-local.
- `fake_execution_node` keeps its name and its `fake_execution_failed` error
  code; renaming is deferred to the API packet that wires production graphs.
