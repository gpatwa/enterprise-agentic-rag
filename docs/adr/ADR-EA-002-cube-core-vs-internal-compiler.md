# ADR-EA-002: Cube Core Versus Narrow Internal Compiler

Status: Accepted for EA-014 implementation

## Decision

Implement the narrow internal PostgreSQL compiler for the first certified
Compass Analytics path. Keep Cube Core behind a future compiler-adapter
decision; do not translate the Compass semantic contract into Cube models yet.

## Evidence

| Criterion | Narrow internal compiler | Cube Core |
|---|---|---|
| Accuracy | Golden tests compile one validated intent to fixed, parameterized PostgreSQL SQL. Unsupported joins, ratios, and required filters fail closed. | Strong semantic-layer capability, but no lossless mapping from the new Compass contract has been specified or tested. |
| Policy | Explicitly rejects metrics requiring policy injection until EA-016 supplies it. | Documents centralized access rules; adopting it would require defining the authoritative policy mapping. |
| Operability | Python module in the existing Analytics API; no extra runtime service for the initial PostgreSQL path. | Self-hosted service; Cube Store is a separate production process for cache/pre-aggregation workloads. |
| Licensing | First-party code. | Cube Backend is Apache 2.0; Cube Client is MIT. Review the exact release before distribution. |
| Latency | Local no-I/O spike: 0.0103 ms/compile over 10,000 runs. This is compiler overhead only, not warehouse latency. | Adds service/API and optional caching layers; no like-for-like local benchmark until a model translation exists. |

Cube sources: [repository and license](https://github.com/cube-js/cube),
[Cube Core documentation](https://docs.cube.dev/cube-core), and
[production Cube Store guidance](https://github.com/cube-js/cube/blob/master/docs-mintlify/cube-core/running-in-production.mdx).

## Consequences

- EA-014 implements the internal compiler only for the contract subset proven
  here: one dataset, supported aggregates, typed filters, temporal grouping,
  sorting, and limits.
- EA-015 and EA-016 must add join-cardinality validation and mandatory policy
  filter injection before this compiler can serve a broader certified path.
- Re-open the Cube adapter decision when a design partner requires Cube's
  multi-source semantic APIs, caching/pre-aggregations, or interoperability.
- This ADR does not treat the query-shape validator as authorization; policy
  authority remains a later dedicated milestone.
