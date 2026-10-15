Status: AI persona advisory review (engineering lead / FinOps). Not an approval or human sign-off; numbers are estimates.

# FinOps / capacity review: ADS-066, ADS-076, M7-H4

Reviewer persona: engineering lead with FinOps and capacity-planning experience. Advisory only. Nothing here changes
code, configuration, thresholds, or the program manifest. Every number marked "estimate" or "assumed" is mine, not a measurement and
not a provider quote.

Inputs read: `ADS-066-quotas-slos.md`, `ADS-076-performance-cost-evaluation.md`, `M7-hardening.md` (M7-H4),
`reports/ADS-076-performance-report.{md,json}`, `reports/M7-H4-cost-calibration-report.md`,
`reference_stack/m7/performance-thresholds.proposed.json`, `quotas/quota-policy.proposed.json`, `app/quotas/*`,
`app/execution/{calibration,gateway,duckdb_gateway,postgres_gateway}.py`, `reference_stack/{performance_eval,calibration_eval,stack,fakes}.py`,
`packages/platform_contracts/{cost_calibration,quotas}.py`, plan section 10.

Local commands run: read-only inspection, plus `python -m reference_stack.calibration_eval <synthetic samples>` on a synthetic file in the
session scratchpad, to confirm the CLI works and what it outputs. No warehouse, network, or deploy.

## Summary

- **The unmet gate is a units problem, not a capacity problem.** `answers_per_tenant_day = 10,000 / mean(8 estimates) = 10,000 / 108.25 = 92.4`.
  The mean mixes two different units: DuckDB's "sum of estimated cardinality across every plan operator" (40 to 263) and a **constant 25**
  returned by the emulated PostgreSQL's `EXPLAIN` stub (`reference_stack/fakes.py`, `_COST = 25.0`). Neither is money, time, or bytes.
  The 10,000 budget and the 100 floor are both placeholders, so the ratio between them tells us nothing about a real tenant.
- **Decision I recommend: calibrate first, then change the gate's definition, then derive the budget from it. Do not lower the 100 floor
  and do not raise the 10,000 budget now.** Change the estimator only if the calibration fit fails its acceptance criteria (DuckDB is the
  likely candidate).
- **The USD gate is dominated by a made-up number.** Of the reported $0.0562 per answer, $0.0541 (96%) is `108.25 units x $0.0005`, the
  placeholder warehouse price. Measured LLM tokens (110 in / 118 out) cost about $0.002 at the placeholder rate, and they cover only the
  intent call on a one-table catalogue. The explanation call is not counted.
- **At pilot volume, fixed infrastructure dominates cost per answer.** My central estimate is about $0.22 per answer fully loaded at
  roughly 16,500 answers a month. LLM is about $0.02 of that, a dedicated warehouse replica about $0.05, and platform infrastructure about
  $0.15. The $0.25 ceiling only makes sense if it states which costs it covers and at what volume.
- **Approve neither file as is.** Amend both (values and definitions are in the table below). The latency gates (8 s P95, 250 ms
  compile/policy) are reasonable to keep as plan-mandated, but the local measurements prove nothing about them. Staging must re-baseline them.
- **Two code findings matter for budgets** (both are advisory and need a human to decide):
  1. The per-run cost cap in the reference stack (`REFERENCE_MAX_COST_UNITS = 10,000`) equals the whole daily budget. ADS-066 bounds overshoot
     by "concurrency x per-run cost", which here allows up to 4 x 10,000, or 400% of the daily budget.
  2. An approved calibration would change the units used by the policy, run-budget, and quota checks (through `CalibratedCostEstimator`).
     The gateways' execute-time check (`ExecutionLimits.max_cost_units`, default 1,000,000) still compares the **raw** `EXPLAIN` number.
     Also, the calibration is wired only in the reference stack (`stack.py`); no application-side loader for an approved calibration exists yet.

## answers_per_tenant_day root cause and decision

### How the number is produced

`reference_stack/performance_eval.py` computes `cost_units = mean(estimated_cost_units)` over 4 questions x 2 engines. It then computes
`answers_per_tenant_day = daily_cost_units / cost_units`, with `daily_cost_units` taken from `quota-policy.proposed.json` (10,000).

| Engine | Estimator (code) | What the unit means | Values on the reference mix |
|---|---|---|---|
| DuckDB | `duckdb_gateway._total_cardinality`: sum of `Estimated Cardinality` over **every** operator in `EXPLAIN (FORMAT JSON)` | Rows touched, counted again at each operator. It ignores column width, Parquet row-group pruning, and bytes scanned. | 200, 263, 40, 263 |
| PostgreSQL (emulated) | `postgres_gateway._explain_cost`: `Plan.Total Cost`. The emulator answers every `EXPLAIN` with a constant 25. | On a real server: planner cost in `seq_page_cost` units. In the emulator: a constant. | 25, 25, 25, 25 |

Mean = (766 + 100) / 8 = 108.25, and 10,000 / 108.25 = 92.4.

### Why this cannot be fixed by tuning

1. **Two incompatible units are averaged.** A production deployment runs one dialect (`QuotaGuardedService` takes a single `dialect`), so
   a cross-dialect mean describes no real tenant.
2. **The PostgreSQL value is synthetic.** On a real warehouse, `Total Cost` for a seq scan plus aggregate over 10M rows is typically in the
   10^5 to 10^6 range (estimate). Against a 10,000-unit daily budget, one such query would block the tenant for the rest of the day.
   Against the 10,000-unit per-run cap in the reference stack, it would be refused outright. So the current budget is not "slightly too
   small". On a real warehouse it would be wrong by orders of magnitude, and the direction depends on the dialect.
3. **The estimates do not predict local cost** (M7-H4 local table). On DuckDB the 200-unit query takes 7.9 ms and the 40-unit query takes
   7.5 ms. At 100 rows everything is fixed overhead. That is expected and is not evidence about the warehouse.
4. **The mean over a fixed 4-question mix is the wrong statistic for a budget.** Budgets are exhausted by the heavy tail, so the budget
   should be sized on a high percentile of a realistic mix.

### Options considered

| Option | Verdict | Reason |
|---|---|---|
| Lower the gate (accept a floor of 92 or 90) | **Reject** | It fits the gate to a placeholder ratio. The plan says thresholds change only with a reviewed rationale, and there is none. |
| Raise the budget (for example to 11,000 so the gate meets) | **Reject now** | It makes the gate meet without making anything true. On a real PostgreSQL, 11,000 planner units is still about one query. |
| Calibrate first | **Do this** | It is the only option that gives the unit a meaning (time or money). The mechanism exists (M7-H4) and is tested. |
| Change the gate's definition | **Do this, together with calibration** | Evaluate the gate per dialect, in the calibrated unit, on a high percentile, and derive the budget from it (definition below). |
| Change the estimator | **Conditional** | Only if the fit fails acceptance. DuckDB's sum of cardinalities is the most likely to fail on Parquet data. A bytes-scanned estimate, or `EXPLAIN ANALYZE` profiling for calibration samples, would be the alternative. |

### Recommended gate definition (for the human owner to decide)

For each production dialect, compute `answers_per_tenant_day = daily_budget_calibrated / P90(calibrated cost per answer over the staging mix)`.
Keep the floor (>= 100 is reasonable; see the volume assumptions below). Derive the budget **from** the floor:
`daily_budget = target_answers_per_tenant_day x P90 cost x headroom (1.5)`. Record that derivation in the policy note. Until an approved
production calibration exists, report the gate as **"not evaluable: uncalibrated"** rather than met or unmet, and keep it blocking for go/no-go.

## Calibration plan

The tool is `python -m reference_stack.calibration_eval samples.json` (run from `services/analytics-api` with `PYTHONPATH=.:../..`). It takes
`[{dialect, estimated_units, observed}]` and does a least-squares fit per dialect. It refuses fewer than 10 samples, constant estimates, or a
non-positive slope. Its output always has `version="proposed"`, `unit="set-by-owner"`, and `valid_for_production=false`. The owner fills
those in and approves. The tool reports R² only; it does not report holdout error. The acceptance checks below must be computed alongside it.

### Unit

Choose the unit by how the target warehouse is billed:

- **Provisioned PostgreSQL (the first customer-shaped target):** `warehouse_ms`, the server-side execution time of the statement. Measure it
  with `EXPLAIN (ANALYZE, BUFFERS)` execution time, or as the `pg_stat_statements` `total_exec_time / calls` delta for the statement. The
  marginal money cost of a query on provisioned capacity is close to zero. The scarce resource is capacity, so time is the honest unit.
  Convert to USD separately as `monthly replica cost / (usable ms per month at target utilisation)`, and keep that conversion out of the fit.
- **Consumption-billed warehouse (if one is selected later):** the billed unit itself (credits, slot-ms, or bytes billed), taken from the
  warehouse's query history for the statement, including the effect of minimum billing increments.
- **DuckDB / data lake:** `warehouse_ms` on the target host and storage tier (object storage, not local SSD).

Use one unit per calibration version. Never mix units across dialects in a single gate.

### Samples to collect (per dialect)

- **How many:** at least **60 distinct compiled plans per dialect**, using 40 to fit and 20 held out. The code minimum of 10 is a floor for
  the mechanism, not a basis for a fit. Run each plan **5 times** and use the median as `observed`. Record cold-cache (first run after a
  buffer reset, or the first of the day) and warm runs separately. Fit on warm runs, and report the cold/warm ratio as its own number.
- **Where from:** staging warehouse with production-shaped volume and statistics (`ANALYZE` up to date), read through the governed gateway
  so the SQL is exactly what the compiler emits. Use only certified metrics in the pilot catalogue.
- **Which shapes (cover at least 2 orders of magnitude in `estimated_units`):** scalar aggregate over a full table, aggregate with a
  selective filter, group by with low and with high cardinality, monthly time series over 1 / 12 / 36 months, top-N, each allowed join path
  in the certified semantic model, the largest permitted date range, and queries that hit and miss indexes or partition pruning.
  Include the 4 reference questions so the local and staging numbers can be compared.
- **Record per sample:** `dialect`, `estimated_units` (the raw gateway estimate, before calibration), `observed`, plus for the review
  only: plan hash, row count returned, cache state, concurrent load during the run, and timestamp. Keep the sample file free of tenant data.
  Plan hashes and numbers are enough.

### Acceptance criteria for a fit (proposed; the owner decides)

1. The tool accepts the samples (no `too_few_samples`, `estimates_do_not_vary`, or `estimates_do_not_predict_cost`).
2. R² >= 0.7 on the fit set. Because the fit is ordinary least squares on raw values, the largest queries dominate R². R² is therefore
   necessary but not sufficient.
3. On the 20 held-out plans: median absolute percentage error <= 35%, and >= 80% of plans within a factor of 2 of the prediction.
4. **No systematic under-prediction in the top decile.** The most expensive held-out plans must not be under-predicted by more than 30% on
   average. Under-predicting the tail is the denial-of-wallet risk.
5. `offset` is non-negative and plausible as fixed per-query overhead (for example, it should not exceed the median `observed`).
6. Re-running the same plans a week later (or after a statistics refresh) changes `scale` by less than 25%. Otherwise, set a
   recalibration cadence.
7. If criteria 2 to 4 fail for DuckDB, change the estimator (bytes scanned or profiled operator cost) rather than loosening the criteria.

After acceptance, the owner sets `unit`, `calibrated_against` (the warehouse, SKU, and data snapshot), `calibration_version`, and
`valid_for_production=true`, and approves with a named person and date. Only then are the gate and the budget recomputed.

### Wiring to confirm before relying on it (advisory code observations)

- `CalibratedCostEstimator` is wired only in `reference_stack/stack.py`. The application needs a loader for an approved calibration
  artifact; otherwise an approval has no effect outside the reference stack.
- After calibration, policy, run-budget, and quota checks use calibrated units. The gateways' execute-time `max_cost_units` check still uses
  raw `EXPLAIN` units. Either calibrate that ceiling too, or document it as a raw-unit safety backstop with its own value per dialect.
- The value labelled "observed" (`observed_cost_units`) is the sum of node-reported planner estimates, not billed cost. Do not report it as
  actual spend.

## Unit-economics model

All values are **estimates with explicit assumptions**. Replace the price bands with the contracted model price, the actual warehouse SKU,
and actual infrastructure invoices.

### Tokens per answer (estimate)

What was measured: mean 110 input / 118 output tokens, for the intent call only. The tokens were counted as characters / 4, on a scripted
model with a one-table catalogue (ADS-072: mean bounded pack 68 tokens; whole-catalogue baseline 308).

| Component | Calls per answer | Input tokens (range) | Output tokens (range) | Assumption |
|---|---:|---:|---:|---|
| Intent extraction | 1 (single attempt, no retry) | 1,500 to 3,500 | 150 to 400 | System prompt and schema 800 to 1,500; bounded context pack 500 to 2,000 (the gate allows 2,000); question 30 to 100 |
| Grounded explanation | 1 | 600 to 1,500 | 150 to 400 | FactSheet plus instructions; this call is not measured by ADS-076 |
| Clarification turns | about 0.15 | +300 to +800 | +50 to +100 | Assumes 10 to 20% of questions need one clarification |
| **Total per answer** | about 2.15 | **about 2,400 to 5,800 (central 4,000)** | **about 350 to 900 (central 600)** | Add 5 to 10% for failed or abandoned runs |

### LLM cost per answer (estimate)

| Price band (assumed, not quotes) | Input $/M | Output $/M | Low | Central | High |
|---|---:|---:|---:|---:|---:|
| Mid/frontier tier (the placeholder $3 / $15 sits here) | 3.00 | 15.00 | $0.012 | $0.023 | $0.034 |
| Small/efficient tier | 0.40 | 1.60 | $0.0015 | $0.003 | $0.004 |

The central figure includes 10% overhead for failed runs. The model choice is worth a 5 to 10x difference in LLM cost. That is still small
next to fixed costs at pilot volume.

### Warehouse cost (estimate)

- **Provisioned PostgreSQL read replica dedicated to analytics:** assumed $400 to $1,200 a month (4 to 8 vCores plus storage; illustrative,
  not a quote). Marginal per-query cost is about zero, so per-answer cost is fixed cost divided by volume. Central assumption: $800 a month.
- **Customer-owned warehouse:** platform cost is about zero, but the customer pays. The calibrated `warehouse_ms` or billed unit is what we
  must show them.
- **Consumption warehouse:** per-query cost from about $0.001 to more than $0.10 depending on scan size and minimum billing increments.
  For sparse interactive traffic, auto-resume minimums can dominate.

### Platform infrastructure (estimate, pilot)

The following are assumed monthly ranges:

- API and runtime compute: $300 to $1,000
- Control-store PostgreSQL (HA): $200 to $600
- Managed OpenSearch: $500 to $1,500
- Observability ingestion and retention: $200 to $800
- Secrets, networking, egress, and backups: $100 to $300

Total: **$1,300 to $4,200 a month, central $2,500.**

### Fully loaded cost per answer (estimate; mid-tier model)

Volume assumption: about 3 pilot tenants x 25 active users x 10 answers per user per working day x 22 days, which is **16,500 answers a
month** (about 250 per tenant per working day).

| Volume per month | LLM | Warehouse replica ($800) | Infrastructure ($2,500) | **Total per answer** |
|---:|---:|---:|---:|---:|
| 5,000 (slow pilot) | $0.023 | $0.160 | $0.500 | **about $0.68** |
| 16,500 (central) | $0.023 | $0.048 | $0.152 | **about $0.22** |
| 50,000 (busy pilot) | $0.023 | $0.016 | $0.050 | **about $0.09** |

Takeaways:

1. The marginal cost per answer (LLM plus variable warehouse) is about $0.003 to $0.035, well under $0.25.
2. Fully loaded cost depends mostly on volume, through the fixed costs.
3. The current `cost_per_answer_usd` gate measures neither of these. Split it into a gated **marginal cost per answer** and a reported
   (not gated) **fully loaded cost at the declared pilot volume**, together with a monthly platform budget.

### Latency model (estimate; replaces nothing, informs staging)

Estimated end-to-end P95 for one answer:

- Intent LLM call: 1.5 to 4 s
- Explanation LLM call: 1 to 3 s
- OpenSearch context retrieval: 0.05 to 0.3 s
- Compile and policy: about 3 ms measured locally; the gate is 250 ms
- `EXPLAIN`: 0.01 to 0.1 s
- Warehouse execution: 0.1 to 5 s
- Evidence and control-store writes: 0.02 to 0.1 s

The sum is about **3.5 to 10 s**, so the 8 s P95 is plausible but at risk, mainly from the two sequential model calls and the warehouse
tail. Locally, concurrent P95 (2.49 s) is about 30x warm P95 (0.08 s) with 8 workers in one process. That in-process contention (SQLite
control store, threads) should be checked on the staging topology before anyone attributes latency to the model.

## Threshold recommendations (table)

### performance-thresholds.proposed.json: **Amend**

| Item | Current | Recommendation | Rationale |
|---|---|---|---|
| `p95_warm_latency_seconds` | <= 8.0 | **Keep 8.0** (plan section 10). Re-measure on staging with the real model and warehouse. Add P99 <= 20 s as reported, not gated. | Plan-mandated. The local value proves only that the deterministic overhead is negligible. |
| `p95_concurrent_latency_seconds` | <= 8.0 at 8 workers | **Keep 8.0, and declare the target concurrency**: the sum of per-tenant caps of the expected concurrently active tenants (estimate 3 x 4 = 12, so test at 12 and 24) | A gate "at target concurrency" with no declared target is not testable. |
| `p95_compile_policy_overhead_ms` | <= 250 | **Keep** | Plan-mandated. 3.3 ms measured leaves wide headroom. |
| `concurrent_errors_or_wrong_rows` | <= 0 | **Keep** | Correctness must not be relaxed for infrastructure. |
| `prompt_tokens_per_intent_max` | <= 2,000 | **Amend**: gate the context pack at <= 2,000 and the **whole intent prompt** at <= 4,000 (estimate). Count with the selected model's tokenizer, not characters / 4. | The measured 110 covers a one-table catalogue; a real system prompt alone may be about 1,000. |
| `cost_per_answer_usd` | <= 0.25, placeholder prices | **Amend**: (a) gate **marginal** cost (LLM, all calls including explanation, plus calibrated variable warehouse) at <= $0.05; (b) report fully loaded cost at the declared pilot volume against a monthly budget, not gated | The current number is 96% placeholder warehouse price. |
| `warehouse_cost_units_per_answer` | <= 150 uncalibrated, mean over both dialects | **Replace**: per dialect, P90 calibrated cost per answer <= a value set after calibration | Uncalibrated units averaged across dialects have no meaning. |
| `answers_per_tenant_day` | >= 100 | **Keep the floor of 100. Change the definition** (per dialect, calibrated, P90; budget derived from the floor). Mark it "not evaluable" until an approved calibration exists. | See the root-cause section. Do not lower the floor, and do not raise the budget to make it meet. |
| `quiet_tenant_denials`, `noisy_tenant_over_quota` | <= 0 | **Keep** | Fairness invariants. They are sound. |
| `assumed_prices` | $3 / $15 per M tokens, $0.0005 per unit | **Replace** with the contracted model price and a `usd_per_calibrated_unit` derived from the warehouse SKU. Keep the "placeholder" label until then. | The per-unit price has no basis while the unit has no meaning. |

### quota-policy.proposed.json: **Amend**

| Item | Current | Recommendation | Rationale |
|---|---|---|---|
| `requests_per_minute` / `burst` | 60 / 20 | **Keep for the pilot** | Not the binding constraint. A 25-user tenant peaks well below this. |
| `max_concurrent_runs` | 4 | **Keep per tenant**, and **add a platform-wide cap**. Size it as min(warehouse pool, model provider rate limit / (tokens per answer x answers per minute)). Estimate 16 to 24 for the pilot. | There is no global cap today. Several tenants at their caps can exceed the replica's or the model provider's capacity. |
| `daily_cost_units` | 10,000 (raw, mixed units) | **Amend after calibration**: `target answers per tenant per day (estimate 250, peak 500) x P90 calibrated cost x 1.5`, in the calibrated unit, per dialect. Use per-tenant overrides for large tenants. | A raw 10,000 would be about one query on a real PostgreSQL. |
| Per-run cost cap (`REFERENCE_MAX_COST_UNITS`, run budget) | 10,000, equal to the daily budget | **Set to no more than 5 to 10% of the daily budget** in the same unit | Overshoot is bounded by concurrency x per-run cost. Today that is 4x the daily budget. |
| Token / USD budget | None (ADS-066 says model cost is not attributed) | **Add** a per-tenant daily token budget, or attribute model tokens into the USD budget | LLM is the only cost that scales per answer when warehouse capacity is provisioned. |
| `warn_fraction` | 0.8 | **Keep** | Standard. |
| `slo.success_target` | 0.99 | **Keep for the pilot.** Re-check against the measured provider error rate, given single-attempt intent calls with no retry. | A provider error rate of 0.5 to 1% alone would consume the budget. |
| `slo.fast/slow burn`, windows, `min_requests` | 14.4 over 5 min / 6 over 1 h, min 20 | **Amend**: evaluate burn rates on the **aggregate across all tenants** as well as per tenant. Consider multi-window pairs (1 h and 5 min for 14.4; 6 h and 30 min for 6). | At about 250 answers per tenant per day (under 1 a minute), a 5-minute window rarely reaches 20 requests, so the per-tenant page will almost never fire. |
| `slo.p95_latency_seconds` | 8 | **Keep**, aligned with the performance gate | Consistent with plan section 10. |
| `approval` | proposed | **Stays proposed.** Only the user approves. | Human gate. |

## Staging measurements required

Each measurement below feeds a named decision. All must be taken on the selected staging model and warehouse with production-shaped data.
None of these can be run from this environment.

| # | Measurement | Method | Feeds decision |
|---|---|---|---|
| 1 | Calibration samples: at least 60 plans per dialect x 5 runs, warm and cold, with `estimated_units` and `observed` | Calibration plan above, then `calibration_eval samples.json` | Approve or reject the calibration; whether to change the DuckDB estimator |
| 2 | Real tokens per answer for every model call (intent, explanation, clarification), using the provider's reported usage, across the M7 corpus | Provider usage fields per call, joined to the run | Context and prompt token gates; LLM cost per answer; model tier choice |
| 3 | Model call latency P50/P95/P99 and provider error/timeout rate, at target concurrency | Per-call timing and outcome | 8 s P95 feasibility; `success_target` 0.99; whether intent needs a retry policy |
| 4 | End-to-end P95/P99 at declared target concurrency (for example 12 and 24) for 30 minutes or more, plus a 2x burst | Load test through the guarded API | `p95_concurrent_latency_seconds`; platform-wide concurrency cap |
| 5 | Warehouse P95 execution time per query shape, and replica CPU/IO at target load | `pg_stat_statements` and host metrics | Per-run cost cap; warehouse SKU; raw-unit execute ceiling per dialect |
| 6 | Control-store PostgreSQL contention: connection pool saturation and checkpoint/evidence write latency | Pool and database metrics during #4 | Control-store sizing; whether the local concurrent-P95 inflation reproduces |
| 7 | OpenSearch retrieval latency and cluster cost at the pilot index size | Query timing; SKU invoice | Infrastructure cost line; latency budget |
| 8 | Infrastructure cost per month for the staging topology scaled to pilot (compute, databases, OpenSearch, observability, egress) | Cost-management export with resource tags per service | Fully loaded cost per answer; monthly platform budget |
| 9 | Pilot demand: users per tenant, questions per user per day, peak-hour share | Pilot sponsor estimate, then first-week telemetry | `answers_per_tenant_day` floor; `daily_cost_units`; per-tenant overrides |
| 10 | Quota behaviour with real costs: budget exhaustion overshoot, alert firing, 429 rate | Guarded API under #4 with calibrated units | Per-run cap as % of daily budget; `warn_fraction`; SLO alert windows |
| 11 | Multi-replica behaviour of in-memory quota state | Run 2 or more API replicas under #4 | Whether a shared quota store (ADS-068) is a go/no-go prerequisite |

## Questions for the human owner

1. Which warehouse and SKU is the pilot target? Is it provisioned (so `warehouse_ms` is the unit) or consumption-billed? Is the warehouse
   ours or the customer's?
2. Which model and tier will staging use, and what is the contracted per-token price and rate limit (TPM/RPM)?
3. What pilot demand do you expect (tenants, active users per tenant, questions per user per day)? This sets the 100-answer floor and the
   budget.
4. Do you accept the gate redefinition: per dialect, calibrated unit, P90, budget derived from the floor, and "not evaluable" until an
   approved calibration exists?
5. Should `cost_per_answer_usd` gate marginal cost only, with fully loaded cost reported against a monthly budget? What is the monthly
   platform budget for the pilot?
6. Who is the named approver for the cost calibration, and how often should it be redone (on warehouse SKU change, on statistics refresh,
   quarterly)?
7. Should the per-run cost cap be set as a fraction of the daily budget (proposed: 5 to 10%)? Should a platform-wide concurrency cap and a
   per-tenant token budget be added before go/no-go?
8. Is a shared, restart-safe quota store a go/no-go prerequisite? In-memory state is lost on restart and is held separately by each replica.
