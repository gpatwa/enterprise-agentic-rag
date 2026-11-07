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

## Live PostgreSQL verification (2026-11-06)

Scope: a throwaway local PostgreSQL only. No cloud, warehouse, or deployed database was touched. The packet status stays
**Review**; this section is evidence for the independent reviewer, not an approval, and the program manifest is unchanged.

Setup
- `postgres:16-alpine` (already cached) as container `par-analytics-pg` on `127.0.0.1:55432`, password generated for the run and not
  recorded. `select version()` returned `PostgreSQL 16.14 on aarch64-unknown-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit`.
- Client stack: Python 3.12.3, SQLAlchemy 2.0.25, psycopg2 2.9.10, sqlglot 30.17.0.
- New opt-in suite `services/analytics-api/tests/test_ads040_postgres_integration.py` (58 tests), skipped unless
  `ANALYTICS_TEST_POSTGRES_URL` is set to a superuser URL of a disposable server (same convention as
  `test_m7_postgres_control_store.py`). It creates its own database and a login role that may `SELECT` only the allowlisted tables,
  loads synthetic data (400 fictional orders including NULL amounts, NULL statuses and 25 customers; a 30,000-row events table;
  a table with spaces, upper case, an embedded quote and a reserved word in its names; a decoy `"Sales_Orders"`; a write-audit
  table, a sequence and a volatile writing function), and drops the database and role afterwards. Expected values are computed in
  Python, not by the server under test.
- Command: `ANALYTICS_TEST_POSTGRES_URL=<superuser url> PYTHONPATH=.:../.. pytest tests/test_ads040_postgres_integration.py
  tests/test_ads040_execution_gateways.py tests/test_warehouse_gateways.py tests/test_postgres_compiler.py -q` from
  `services/analytics-api`: 144 passed, three consecutive runs (about 10 to 18 seconds each). Without the variable the new
  module is skipped.

What the live run confirmed
- Compiler output executes on the server and matches the Python computation: SUM/AVG/MIN/MAX/COUNT/COUNT(DISTINCT) with NULL
  amounts and a NULL group, `IN`/`NOT IN`/comparison filters, a datetime time range (inclusive and exclusive end), all five time
  granularities (day, week, month, quarter, year), multi-key sort and `LIMIT`, `HAVING` for `min_cohort`, quoting of names with
  spaces, quotes and reserved words, and a hostile string value bound as data. Sums stay `Decimal`.
- Read-only: 22 unsafe or out-of-scope statements (DML, DDL, COPY, SELECT INTO, FOR UPDATE, data-modifying CTE, stacked
  statements, `nextval`, `pg_sleep`, `set_config`, catalog and information_schema reads) are refused before any connection is
  opened. With the AST guard disabled and a table-owner connection, the server itself refused a writing function, `nextval` and
  `set_config('transaction_read_only', 'off', true)` (the audit table and sequence were unchanged), and the read-only role was
  refused a table outside its grants. `SHOW` inside the transaction reported `transaction_read_only=on`, the requested
  `statement_timeout` and `lock_timeout`, and `TimeZone=UTC`; none of these settings leaked to the next user of the pooled connection.
- Limits: row cap (2,500 of 30,000, ordered prefix; exact fit not truncated), byte cap, cost ceiling refusing a cross join from
  `EXPLAIN` in under 5 seconds, `statement_timeout` stopping a runaway query at about 1 second, and mid-run cancellation
  (`psycopg2` `cancel()`) reported as cancelled, not as a timeout, well inside a 20 second timeout. After truncation, timeout,
  cancel, error and a backend killed with `pg_terminate_backend`, no connection stayed checked out, no server cursor remained
  (`pg_cursors`), no session stayed active, and the pool served the next query. Three concurrent executions returned correct,
  separate results.
- Error mapping: server errors surface as `query failed: <ExceptionType>` only (for example `UndefinedColumn`, `DivisionByZero`,
  `InvalidTextRepresentation`); a wrong password and an unreachable host leak none of the password, host, port, database name or table
  names in the message or repr of the raised error.

Defects found and fixed (each has a unit test in `test_ads040_execution_gateways.py` that fails without the fix)
1. Allowlist bypass by identifier case: the validator lower-cased every table name, but PostgreSQL treats a quoted `"Sales_Orders"`
   as a different table from `sales_orders`, so a quoted name passed the `sales_orders` allowlist and, on the live server, returned
   the decoy's rows. `validate_read_only_sql` gained `case_sensitive_quoted` (default off, so DuckDB and the warehouse gateways are
   unchanged); `PostgresGateway` now compares quoted names exactly, folds unquoted names to lower case as the server does, and
   keeps allowlist entries as exact physical names (the compiler already quotes the contract's physical name exactly).
2. A token cancelled before `execute` did not stop the query: the driver cancel sent to an idle connection is dropped by the
   server, so the statement ran until `statement_timeout` (4 seconds in the probe; DuckDB already guarded this). The gateway now
   raises `ExecutionCancelled` before connecting and again right after binding the hook.
3. An unbound `:pN` marker raised SQLAlchemy `StatementError` carrying the full SQL text and was not an `ExecutionError`. It is now
   a `QueryRejected` before any connection (execute and estimate).
4. Any non-DBAPI exception during `execute` (pool exhaustion, adapter and bind errors) escaped as a raw SQLAlchemy exception
   instead of an `ExecutionError`; it now maps to `query failed: <ExceptionType>`.

Observations, not changed
- PostgreSQL sorts NULLs first for `DESC` and last for `ASC`, and the compiler emits no `NULLS FIRST/LAST`, so a descending
  "top N" can lead with NULL aggregates (and DuckDB's default differs). Pinned by a characterisation test; changing the compiled
  SQL is a decision for the compiler owner because it alters byte-identical plans.
- `ExecutionError` keeps the driver exception as `__cause__` (as the warehouse gateways do); the message is clean, but a caller
  that logs full tracebacks would record the driver's text, including the host on connection failures.
- A cancel that lands in the gap between the post-bind check and the server starting the statement is still dropped; the
  `statement_timeout` bound then applies. Unqualified table names resolve through the role's `search_path`; pin it on the role.

Not verified
- The stalled-link watchdog (`timeout + 1s` timer), TLS, pgbouncer or other poolers, other PostgreSQL versions (only 16.14), a
  non-superuser deployment role created by real provisioning, large-result memory behavior, and any
  managed (Azure) PostgreSQL. The explicit live-deployment gate in the Boundary section above is unchanged.
- The full analytics suite result is recorded in the pull request.
