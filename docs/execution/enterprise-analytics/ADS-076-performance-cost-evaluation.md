# ADS-076: Latency, Concurrency, Token, Warehouse, and Infrastructure Cost Evaluation

Status: **Review** (local measurements; thresholds and prices **proposed placeholders**; **one gate does not meet**)
Milestone: M7 (wave 7B)
Depends on: ADS-066

## Decisions made under the user's delegation ("make the decision")

1. **Measure what exists, label what does not.** Warm latency (200 requests over both dialects), concurrency (8 workers x 20 requests per dialect, 320 requests), deterministic compile/policy overhead,
   tokens per intent (prompt and reply sizes recorded from the model boundary), warehouse cost units per answer, and tenant fairness under a scripted overload with the ADS-066 simulator.
2. **Unit economics use an assumed price table** (`assumed_prices` in the thresholds file: USD per million input/output tokens and per warehouse cost unit). These are placeholders to make the arithmetic
   possible, not quotes from any provider; the report says so.
3. **The plan's latency gates are applied unchanged** (P95 <= 8 s, compile/policy <= 250 ms). They pass by two to three orders of magnitude because the model is scripted and the data is 100 rows: this shows the
   deterministic layer adds negligible overhead, not that a real deployment meets 8 seconds.

## Result and the gate that does not meet

All gates meet except **`answers_per_tenant_day` (92 against a proposed 100)**. The estimator's cost units are uncalibrated and vary from 25 to 263 per answer by query and dialect; against the ADS-066 proposed daily budget of 10,000
units a tenant affords about 92 answers a day on this mix. The gate was proposed by the implementing agent and **left unmet rather than lowered**. The user's decision: calibrate the cost units to the real warehouse,
raise the proposed daily budget, or accept a lower floor. Nothing else was tuned to this result.

## Deliverable

- `reference_stack/performance_eval.py`, `m7/performance-thresholds.proposed.json`, `make analytics-m7-performance` (exits non-zero while a gate is unmet), report `reports/ADS-076-performance-report.{md,json}`, `tests/test_ads076_performance.py`

## Boundary

- Scripted model, 100-row DuckDB, an emulated PostgreSQL, a SQLite control store: **real model latency, warehouse latency and cost, PostgreSQL contention, and infrastructure (compute, storage, network) cost are not measured.** No target load is declared.
- Approval of the thresholds and the prices is the user's; the plan requires latency and cost to be re-baselined for the selected staging model and warehouse.
