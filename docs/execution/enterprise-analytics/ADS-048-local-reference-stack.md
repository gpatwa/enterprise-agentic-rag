# ADS-048: Local Reference Stack and Seeded PostgreSQL/DuckDB Demos

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M4
Depends on: ADS-040, ADS-044 to ADS-047

**Fakes only.** No network connection, no PostgreSQL server, no OpenSearch, no cloud. DuckDB is
real and embedded. The "PostgreSQL" journey runs the real `PostgresGateway` and
`PostgreSQLCompiler` against an *emulated* engine, so Postgres-dialect SQL, the read-only and
timeout session statements, the EXPLAIN cost gate, and rollback are exercised, but no
PostgreSQL server is. This is not live PostgreSQL validation.

## Deliverable

`services/analytics-api/reference_stack/` (outside `app/`; never imported by `app.main`):

- `fakes.py`: deterministic seed (`sales_orders`, 100 orders, Jan-Mar 2024, written to Parquet);
  a scripted, schema-valid intent client (monthly revenue, revenue by status, total revenue;
  anything else is malformed output); a scripted explainer that quotes only the cells it
  cites; snapshot, search, ontology, and contract providers derived from the certified
  `sales-core@v1` contract (nothing is promoted); and `EmulatedPostgresEngine`, which
  transpiles Postgres SQL to DuckDB and runs it over the seeded file.
- `stack.py`: `build_stack(engine)` creates the seed, a migrated SQLite control store, the
  gateway and compiler for the chosen dialect, and wires the full graph-v2 (retrieval through
  `explain`), the ADS-045 service, and a locally signed OIDC verifier into a FastAPI app via
  `ReferenceStack.app()`. Tokens are HS256 with a per-stack random secret, so they work only
  against the stack that minted them.
- `smoke.py`: one 13-step journey per dialect, plus a cross-dialect check: auth (401), purpose
  (403), grounded answer, three-row result with a line spec, idempotent replay, evidence sealing
  and chain verification, revenue by status, ungrouped stat, unsupported question failing
  safely, review pause, self-approval refused, reviewer approval, and the approved answer
  matching the unreviewed one. Rows must be identical across DuckDB and the Postgres emulation.
- Commands (from the repo root): `make analytics-reference-smoke` (both journeys, exit code 1 on
  any failure) and `make analytics-reference-up` (serve the v2 API on `127.0.0.1:8095` and print
  local test tokens). `python -m reference_stack smoke --engine duckdb|postgres|both [--json]`.

## Evidence

- `make analytics-reference-smoke`: both journeys PASS, cross-dialect rows identical.
- `services/analytics-api/tests/test_ads048_reference_stack.py` (7 tests): both journeys pass with
  socket connections forbidden; the journey covers the governed boundaries; the Postgres journey
  issues `SET TRANSACTION READ ONLY` and `statement_timeout` and rolls back every transaction;
  tokens are not portable between stacks; deterministic seed and schema-bound scripted model; CLI
  exit code and output; the production app's `v2_runtime` stays unset.
- `make analytics-reference-up` served a real answer over HTTP on a free port (manual check).
- Finding: with the default run budget (100 cost units) DuckDB's planner-cardinality cost
  rejected unfiltered queries (`cost_budget_exceeded`). This is the known uncalibrated
  per-dialect cost seam from ADS-040, now observed. The reference stack sets an explicit
  `max_cost_units=10_000`; the gateways were not changed and calibration remains open.

## Boundary

- Not live: no PostgreSQL server, OpenSearch, OpenMetadata/dbt, warehouse, or model. The
  emulation cannot reveal Postgres-specific semantics (NULL ordering, planner behavior, role
  grants, the append-only triggers in migration `0004`).
- The scripted model recognises three phrasings; it demonstrates the pipeline, not language
  understanding. Answers and explanations are in process-local stores, as in ADS-045.
- The journeys use the seeded `sales-core` contract only; the Olist demo data is not part of this
  stack. Review thresholds and budgets are reference values, not calibrated policy.
- The stack ships in the analytics-api image because it lives under `services/analytics-api`;
  nothing starts it there. Move or exclude it if that is unwanted.
- This packet does not satisfy ADS-049: no golden report or correctness/trust gates are
  evaluated here, and the M4 `local_demo_review` human gate is untouched.
