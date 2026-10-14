# ADS-076: Latency, Concurrency, Token, Warehouse, and Infrastructure Cost Evaluation

**Result: DOES NOT MEET the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. Measured on a scripted model, local DuckDB, an emulated PostgreSQL, and a SQLite control store: **these numbers say nothing about a real model or warehouse**, and the plan requires latency and cost to be re-baselined for the staging stack.

200 warm requests, 320 concurrent requests (8 workers per engine), throughput {'duckdb': 10.2, 'postgres': 12.9} requests/s, warehouse cost units per answer 25 to 263 (uncalibrated, per dialect) against a proposed daily budget of 10000; warm latency p50 47 ms, p95 82 ms, p99 187 ms; mean tokens per intent 110 in / 118 out; peak RSS 211.6 MB.

## Metrics

| Metric | Measured | Gate | Meets | Plan gate |
|---|---:|---:|:---:|---|
| `p95_warm_latency_seconds` | 0.08196 | <= 8.0 | yes | P95 warm answer latency, local reference data <= 8 seconds |
| `p95_concurrent_latency_seconds` | 2.486 | <= 8.0 | yes | P95 at target concurrency <= 8 seconds |
| `p95_compile_policy_overhead_ms` | 3.26 | <= 250.0 | yes | P95 deterministic compile/policy overhead <= 250 ms |
| `concurrent_errors_or_wrong_rows` | 0 | <= 0 | yes | No errors or wrong rows under concurrency: 0 |
| `prompt_tokens_per_intent_max` | 110 | <= 2000 | yes | Context tokens per intent stay within the run's context budget |
| `cost_per_answer_usd` | 0.05623 | <= 0.25 | yes | Unit economics: assumed cost per answered question within the proposed ceiling |
| `warehouse_cost_units_per_answer` | 108.2 | <= 150 | yes | Warehouse cost units per answer (mean over the question mix) within the proposed ceiling |
| `quiet_tenant_denials` | 0 | <= 0 | yes | A noisy neighbour does not deny a quiet tenant: 0 |
| `noisy_tenant_over_quota` | 0 | <= 0 | yes | A tenant above its quota is held to it: 0 admissions above the allowed |
| `answers_per_tenant_day` | 92.38 | >= 100 | **NO** | The proposed daily cost budget affords a tenant at least this many answers a day |

## Tenant fairness under overload (ADS-066 simulator)

In 120 simulated seconds the noisy tenant offered 1200 requests and was admitted 139 (at most 144 allowed; denied {'concurrency_limited': 5, 'rate_limited': 1056}); the quiet tenant offered 120, was admitted 120, denied none.

## Assumed prices (placeholders, not quotes)

`{'usd_per_million_input_tokens': 3.0, 'usd_per_million_output_tokens': 15.0, 'usd_per_warehouse_cost_unit': 0.0005, 'note': 'PLACEHOLDERS chosen by the implementing agent so that unit economics can be computed; not quotes from any provider or warehouse. Replace with the selected model and warehouse prices.'}`

## Not measured

- **real_model_latency**: the model is scripted and instant; a real model call typically dominates latency and cost and is the largest unknown
- **real_warehouse**: DuckDB over a 100-row table and an emulated PostgreSQL say nothing about warehouse latency, scan cost, or concurrency
- **target_load**: no target load is declared; 8 concurrent workers on one process is a smoke test, not a capacity test
- **control_store**: the control store is SQLite in a local file; PostgreSQL contention and connection pooling are not measured
- **infrastructure_cost**: compute, storage, network, and observability costs are not modelled; only model tokens and warehouse cost units are
- **token_baseline**: the plan's -20% target is against the ADS-007 baseline, which this evaluation does not compare to (see ADS-072 for the retrieval-side token reduction)
