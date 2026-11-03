# Analytics: Snowflake and Databricks provider scope

Status: **Scoping proposal.** Written 2026-11-03 from `origin/main` (`c2fcb25`). Nothing here is an approval or a recorded human gate. No code is written, no warehouse is contacted and no cloud resource is touched. Connecting to a live warehouse needs your explicit request in a later task (`CLAUDE.md`); everything below is verifiable locally with fake providers.

## Authorization and progress (2026-11-03)

Owner, in chat: "authorize W1 to W7 local-only, start with W1 and complete till W7". Recorded here from the owner's words; this is not a manifest entry and says nothing about W8 (live validation), W9 or any threshold.

Built and tested locally with fakes only (no warehouse, no driver, no cloud):

| Packet | State | Evidence |
|---|---|---|
| W1 conformance harness | Done | `tests/test_dialect_conformance.py`: four dialects (postgres, duckdb, snowflake, databricks) x four intents compile to parseable read-only SQL with equal bind parameters; golden SQL per dialect; registry fails closed on an unknown dialect; refusal tests for unquotable names |
| W2 and W5 compiler adapters | Done | `SnowflakeCompilerAdapter`, `DatabricksCompilerAdapter`, `app/compiler/dialects.py` (the PostgreSQL and DuckDB output is unchanged: existing compiler tests still pass) |
| W3 and W7 metadata providers | Done | `app/metadata/warehouse_providers.py`, `tests/test_warehouse_metadata_providers.py`; a missing or invisible table raises instead of returning an empty asset |
| W4 and W6 gateways | **Policy layer done; no real driver session** | `app/execution/warehouse_gateway.py`, `tests/test_warehouse_gateways.py` against a scriptable fake session |

What "done" does **not** mean:

- The real Snowflake and Databricks sessions (connect, apply the statement timeout and read-only settings, `EXPLAIN` cost, cancel, row streaming, marker syntax) are not written. They need a live warehouse to verify and are part of W8. Until then the gateways cannot run a query against either engine.
- Generated SQL is validated with `sqlglot`'s Snowflake and Databricks parsers only. It has not been run on either engine, so engine-specific behavior (time-zone handling of the timezone-aware bind values, `TIMESTAMP_NTZ` comparisons, case folding of unquoted names) is untested.
- Result value normalization across engines (decimal precision, timestamps, large integers) is not done.
- The default is fail-closed on cost: a session that returns no estimate makes the query not run unless `require_cost_estimate=False` is set explicitly.
- Snowflake contracts must state the physical case of names (usually upper case); table names may be `database.schema.table`, and a name with `:`, `%`, `;`, a backslash, whitespace at either end or a control character is refused at compile time for the two new dialects only.
- No semantic contract targets either warehouse yet, and nothing selects these adapters at runtime: `CertifiedIntentCompiler` still defaults to PostgreSQL.

## 1. Why, and what exists

Auto Ontology (parked) supports Snowflake and Databricks; Analytics does not. A repo-wide search found no Snowflake or Databricks code, only competitor mentions in docs and marketing copy. Analytics today targets PostgreSQL (first customer-shaped target) and DuckDB (embedded), plus metadata from Postgres, dbt manifest, OpenMetadata and DuckDB.

A new warehouse touches three seams, all already defined by protocols:

| Seam | Where | What a new target adds |
|---|---|---|
| Metadata | `app/metadata/providers.py` (`MetadataProvider.get_snapshot`) | A read-only provider that normalizes tables and columns into `MetadataSnapshot` |
| Compiler | `app/compiler/adapter.py` (`CompilerAdapter`, `CompilerRegistry`) | A dialect adapter. Today `DuckDBCompilerAdapter` just subclasses the PostgreSQL compiler with a different tag; that will not be safe for these two. |
| Execution | `app/execution/gateway.py` (`ExecutionGateway`: `estimate`, `execute` with `ExecutionLimits`, `CancellationToken`, `ResultAccumulator`), `validate_read_only_sql` | A gateway enforcing read-only, timeout, row and byte caps, cancellation and a cost estimate, and refusing a plan compiled for another dialect |

The warehouse URL must stay separate from the control-store URL (`config.py` already documents this).

## 2. Dialect and driver risks to resolve (unverified: from a web search and general knowledge, not tested)

- **Identifier handling.** Snowflake folds unquoted identifiers to upper case; Databricks uses backticks and a three-level `catalog.schema.table` namespace under Unity Catalog. The PostgreSQL compiler's quoting and `DATE_TRUNC('month', col)` output cannot be assumed to carry over. Identifiers come from certified contracts, but quoting rules still need golden-SQL tests per dialect.
- **Parameter binding.** The Snowflake connector defaults to client-side `pyformat` binding, and `qmark`/`numeric` give server-side binding ([Snowflake docs](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api.html)). Databricks parameter syntax is not confirmed by my search: a REST-format example was found, not the connector's own. Both must be checked against official docs before any gateway is written.
- **Timeouts and cancellation.** Snowflake: a session parameter `STATEMENT_TIMEOUT_IN_SECONDS` is documented in third-party sources; read-only-role interaction not found. Databricks: a Superset PR says the connector's `Cursor.cancel()` works only with the SEA backend, not the default Thrift one ([PR](https://github.com/apache/superset/pull/42900)); cancel also exists on the REST Statement Execution API. Cancellation is a hard requirement of `ExecutionGateway`, so this decides the Databricks design.
- **Cost estimates.** `estimate()` returns cost units. Neither engine's equivalent was researched; Databricks SQL warehouses may also cold-start, adding latency.
- **Read-only enforcement.** Defense in depth: the Python `validate_read_only_sql` plus a customer-provisioned read-only role or grants. The role setup is the customer's admin task; I did not verify how each engine behaves when a write is attempted under it.
- **Types.** Decimal precision, timestamps with time zone and large integers need explicit result normalization, or sealed evidence will differ by engine.
- **Compiler limits.** `PostgreSQLCompiler` documents one physical dataset per query with no joins or ratios, with later milestones; `join_validation.py` exists. Which of these a warehouse customer needs is unverified.

## 3. Work packets (local only; names are placeholders, not manifest IDs)

| ID | Work | Needs | Evidence |
|---|---|---|---|
| W0 | Decisions in section 6 | **Owner** | Recorded in the program manifest in the owner's words |
| W1 | **Dialect conformance harness:** run the same certified intents through each registered compiler and an in-memory fake gateway; golden SQL per dialect; assert dialect-mismatch refusal. Retrofit PostgreSQL and DuckDB first | none | CI green on existing dialects; harness fails closed on an unregistered dialect |
| W2 | **Snowflake compiler adapter:** its own class, quoting and case rules, parameter style | W1, W0 | Golden SQL tests incl. injection-shaped identifiers, time bucketing, filters, min-cohort `HAVING` |
| W3 | **Snowflake metadata provider** over `information_schema` through an injected connection | W1 | Fake-connection tests; read-only; asset ids stable; no credentials in snapshots or logs |
| W4 | **Snowflake gateway** with an injected fake driver: read-only validation, statement timeout, caps, cancellation hook, error mapping to stable codes, no SQL or values echoed | W2 | Tests mirroring `test_ads040_execution_gateways.py` |
| W5 to W7 | Same three packets for **Databricks**, with Unity Catalog naming and the cancellation design from section 2 | W1, W0 | Same |
| W8 | **Live validation** against a sandbox warehouse: one metadata read, one compiled query, one cancel, one timeout | **Separate explicit authorization**, credentials from you | A recorded run; never a customer's production warehouse |
| W9 | **Draft generator** (the schema to draft-contract gap): read a metadata snapshot and emit draft-only contracts into the existing review path; never certified automatically | W3 or W5 | Output diffed against `olist-commerce-v1`; labeled uncertified |

Order: W1 first regardless of target (it also hardens PostgreSQL and DuckDB). Then Snowflake or Databricks by your choice, then W9.

## 4. Packaging and safety

- Drivers (`snowflake-connector-python`, `databricks-sql-connector`) are optional extras imported lazily, so the default image and CI do not gain them until W8. Versions to pin are unchecked.
- Credentials: environment or Key Vault only, never in the control store, logs, evidence or snapshots. How customers authorize (key-pair or OAuth for Snowflake; token or OAuth for Databricks) is a security gate, not mine.
- Tenant isolation: each tenant has its own gateway and rebuilder (see `ExecutionResultStore`); a warehouse gateway must keep that property.
- Schema and table allowlists per tenant, as the DuckDB gateway does for files.

## 5. Cost

No cloud cost until W8. A sandbox needs a Snowflake trial or a Databricks workspace; trial terms, credits and free tiers were not checked. Compute for a live run is billed by the vendor.

## 6. Decisions for the owner

1. Which warehouse first: Snowflake or Databricks? Is there a design-partner or customer driving it?
2. Sandbox for W8: do you have accounts, and will you supply credentials yourself?
3. Auth methods to support (and the security review of them).
4. Authorize W1 to W7 as local-only work now, with W8 as a later separate approval?
5. Include W9 (draft generator) in the same effort, or later?
6. Do the compiler's current limits (single dataset, no joins or ratios) matter for the first warehouse customer?

## 7. Unverified

Driver parameter syntax for Databricks; Snowflake read-only-role behavior; cost estimation APIs; cancellation under the default Databricks backend; trial terms; whether DuckDB-style dialect reuse is safe for either engine (I expect not); Auto Ontology claims (README only, not run).
