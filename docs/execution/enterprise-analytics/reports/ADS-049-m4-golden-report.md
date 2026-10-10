# ADS-049: Milestone-4 Golden Report

Generated 2026-10-09 06:41 UTC by `make analytics-golden`. Suite `m4-golden-v1`, corpus `e1768f2f8348`, engines: duckdb, postgres.

**Result: MEETS the approved thresholds.** The thresholds were approved by user on 2026-10-08 (scope: local M4 reference-stack thresholds only). This is not the M4 `local_demo_review` approval and does not imply it; no packet has had independent review.

## Scope and limits

- Scripted model (three phrasings plus adversarial inputs), seeded 100-row table, DuckDB, and an **emulated** PostgreSQL. Nothing here measures language understanding, real PostgreSQL behavior, a live index, or a real model.
- Expected rows were computed independently in plain Python from the seed formula, not from the system under test.
- Latency/overhead percentiles come from small samples (60 answered calls); treat them as a smoke signal.

## Metrics against approved thresholds

| Metric | Measured | Gate | Meets | Plan gate |
|---|---:|---:|:---:|---|
| `p0_result_equivalence` | 1 | >= 1.0 | yes | P0 question result equivalence 100% |
| `answer_result_equivalence` | 1 | >= 0.95 | yes | Full answer-case result equivalence >= 95% |
| `refusal_recall` | 1 | >= 1.0 | yes | Unsupported or unsafe request refusal recall 100% |
| `clarify_or_review_recall` | 1 | >= 0.95 | yes | Ambiguous request clarify-or-review recall >= 95% |
| `policy_and_tenant_violations` | 0 | <= 0 | yes | Policy and tenant-isolation violations 0 |
| `raw_model_sql_executed` | 0 | <= 0 | yes | Executed queries authored as raw model SQL 0 |
| `evidence_completeness` | 1 | >= 1.0 | yes | Required evidence completeness 100% |
| `replay_fingerprint_equivalence` | 1 | >= 1.0 | yes | Replay fingerprint equivalence 100% |
| `dialect_result_equivalence` | 1 | >= 1.0 | yes | PostgreSQL/DuckDB portable-subset result equivalence 100% |
| `budget_overruns` | 0 | <= 0 | yes | Runs exceeding loop/transition budget 0 |
| `p95_answer_latency_seconds` | 0.04599 | <= 8.0 | yes | P95 warm answer latency, local reference data <= 8 seconds |
| `p95_compile_policy_overhead_ms` | 0.5783 | <= 250.0 | yes | P95 deterministic compile/policy overhead <= 250 ms |

## Cases

| Case | Engine | Kind | Result | Detail |
|---|---|---|:---:|---|
| G01 | duckdb | answer | pass |  |
| G02 | duckdb | answer | pass |  |
| G03 | duckdb | answer | pass |  |
| G04 | duckdb | answer | pass |  |
| G05 | duckdb | answer | pass |  |
| G06 | duckdb | answer | pass |  |
| R01 | duckdb | refuse_no_execution | pass |  |
| R02 | duckdb | refuse_no_execution | pass |  |
| R03 | duckdb | refuse_no_execution | pass |  |
| R04 | duckdb | refuse_no_execution | pass |  |
| P01 | duckdb | policy_denied | pass |  |
| T01 | duckdb | tenant_isolation | pass |  |
| A01 | duckdb | clarify | pass |  |
| V01 | duckdb | review | pass |  |
| G01 | postgres | answer | pass |  |
| G02 | postgres | answer | pass |  |
| G03 | postgres | answer | pass |  |
| G04 | postgres | answer | pass |  |
| G05 | postgres | answer | pass |  |
| G06 | postgres | answer | pass |  |
| R01 | postgres | refuse_no_execution | pass |  |
| R02 | postgres | refuse_no_execution | pass |  |
| R03 | postgres | refuse_no_execution | pass |  |
| R04 | postgres | refuse_no_execution | pass |  |
| P01 | postgres | policy_denied | pass |  |
| T01 | postgres | tenant_isolation | pass |  |
| A01 | postgres | clarify | pass |  |
| V01 | postgres | review | pass |  |

## Not measured at M4

- **certified_top3_recall**: needs a retrieval corpus and a live index; covered by ADS-072
- **context_tokens_per_intent**: needs a baseline and a real model; covered by ADS-072/ADS-076
- **unreviewed_correction_promotions**: corrections do not exist until M5
- **critical_high_security_defects**: needs an independent security review, not a test run

## Decisions that remain with the user

- The M4 `local_demo_review` human gate, and independent review of ADS-040 to ADS-049.
- M1 semantic certification and any live PostgreSQL/OpenSearch/OpenMetadata validation.
