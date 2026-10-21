# ADS-071: End-to-End Correctness and Dialect Equivalence (M7 reference corpus)

Generated 2026-10-21 11:09 UTC by `make analytics-m7-correctness`. Suite `m7-reference-v1`, corpus `42c25cc23384`, engines: duckdb, postgres.

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. This is not an approval of anything and does not imply one; no packet has had independent review.

> **Approval status:** thresholds are `proposed`; the corpus approvals are `proposed` (definition owner and results owner have not approved). A pass here is not a go/no-go.

## Scope and limits

- Scripted model (the ADS-070 phrasings plus adversarial inputs), seeded 100-row table, DuckDB, and an **emulated** PostgreSQL. Nothing here measures language understanding, real PostgreSQL behavior, a live index, or a real model.
- Expected rows were computed independently in plain Python from the seed formula, not from the system under test.
- Latency/overhead percentiles come from small samples (600 answered calls); treat them as a smoke signal.

## Metrics against proposed thresholds

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
| `p95_answer_latency_seconds` | 0.04956 | <= 8.0 | yes | P95 warm answer latency, local reference data <= 8 seconds |
| `p95_compile_policy_overhead_ms` | 1.33 | <= 250.0 | yes | P95 deterministic compile/policy overhead <= 250 ms |

## Cases

| Case | Engine | Kind | Result | Detail |
|---|---|---|:---:|---|
| A001 | duckdb | answer | pass |  |
| A002 | duckdb | answer | pass |  |
| A003 | duckdb | answer | pass |  |
| A004 | duckdb | answer | pass |  |
| A005 | duckdb | answer | pass |  |
| A006 | duckdb | answer | pass |  |
| A007 | duckdb | answer | pass |  |
| A008 | duckdb | answer | pass |  |
| A009 | duckdb | answer | pass |  |
| A010 | duckdb | answer | pass |  |
| A011 | duckdb | answer | pass |  |
| A012 | duckdb | answer | pass |  |
| A013 | duckdb | answer | pass |  |
| A014 | duckdb | answer | pass |  |
| A015 | duckdb | answer | pass |  |
| A016 | duckdb | answer | pass |  |
| A017 | duckdb | answer | pass |  |
| A018 | duckdb | answer | pass |  |
| A019 | duckdb | answer | pass |  |
| A020 | duckdb | answer | pass |  |
| A021 | duckdb | answer | pass |  |
| A022 | duckdb | answer | pass |  |
| A023 | duckdb | answer | pass |  |
| A024 | duckdb | answer | pass |  |
| A025 | duckdb | answer | pass |  |
| A026 | duckdb | answer | pass |  |
| A027 | duckdb | answer | pass |  |
| A028 | duckdb | answer | pass |  |
| A029 | duckdb | answer | pass |  |
| A030 | duckdb | answer | pass |  |
| A031 | duckdb | answer | pass |  |
| A032 | duckdb | answer | pass |  |
| A033 | duckdb | answer | pass |  |
| A034 | duckdb | answer | pass |  |
| A035 | duckdb | answer | pass |  |
| A036 | duckdb | answer | pass |  |
| A037 | duckdb | answer | pass |  |
| A038 | duckdb | answer | pass |  |
| A039 | duckdb | answer | pass |  |
| A040 | duckdb | answer | pass |  |
| A041 | duckdb | answer | pass |  |
| A042 | duckdb | answer | pass |  |
| A043 | duckdb | answer | pass |  |
| A044 | duckdb | answer | pass |  |
| A045 | duckdb | answer | pass |  |
| A046 | duckdb | answer | pass |  |
| A047 | duckdb | answer | pass |  |
| A048 | duckdb | answer | pass |  |
| A049 | duckdb | answer | pass |  |
| A050 | duckdb | answer | pass |  |
| A051 | duckdb | answer | pass |  |
| A052 | duckdb | answer | pass |  |
| A053 | duckdb | answer | pass |  |
| A054 | duckdb | answer | pass |  |
| A055 | duckdb | answer | pass |  |
| A056 | duckdb | answer | pass |  |
| A057 | duckdb | answer | pass |  |
| A058 | duckdb | answer | pass |  |
| A059 | duckdb | answer | pass |  |
| A060 | duckdb | answer | pass |  |
| R001 | duckdb | refuse_no_execution | pass |  |
| R002 | duckdb | refuse_no_execution | pass |  |
| R003 | duckdb | refuse_no_execution | pass |  |
| R004 | duckdb | refuse_no_execution | pass |  |
| R005 | duckdb | refuse_no_execution | pass |  |
| R006 | duckdb | refuse_no_execution | pass |  |
| R007 | duckdb | refuse_no_execution | pass |  |
| R008 | duckdb | refuse_no_execution | pass |  |
| R009 | duckdb | refuse_no_execution | pass |  |
| R010 | duckdb | refuse_no_execution | pass |  |
| R011 | duckdb | refuse_no_execution | pass |  |
| R012 | duckdb | refuse_no_execution | pass |  |
| R013 | duckdb | refuse_no_execution | pass |  |
| R014 | duckdb | refuse_no_execution | pass |  |
| R015 | duckdb | refuse_no_execution | pass |  |
| R016 | duckdb | refuse_no_execution | pass |  |
| D001 | duckdb | policy_denied | pass |  |
| D002 | duckdb | policy_denied | pass |  |
| D003 | duckdb | policy_denied | pass |  |
| D004 | duckdb | policy_denied | pass |  |
| T001 | duckdb | tenant_isolation | pass |  |
| T002 | duckdb | tenant_isolation | pass |  |
| T003 | duckdb | tenant_isolation | pass |  |
| T004 | duckdb | tenant_isolation | pass |  |
| C001 | duckdb | clarify | pass |  |
| C002 | duckdb | clarify | pass |  |
| C003 | duckdb | clarify | pass |  |
| C004 | duckdb | clarify | pass |  |
| C005 | duckdb | clarify | pass |  |
| C006 | duckdb | clarify | pass |  |
| C007 | duckdb | clarify | pass |  |
| C008 | duckdb | clarify | pass |  |
| V001 | duckdb | review | pass |  |
| V002 | duckdb | review | pass |  |
| V003 | duckdb | review | pass |  |
| V004 | duckdb | review | pass |  |
| V005 | duckdb | review | pass |  |
| V006 | duckdb | review | pass |  |
| V007 | duckdb | review | pass |  |
| V008 | duckdb | review | pass |  |
| A001 | postgres | answer | pass |  |
| A002 | postgres | answer | pass |  |
| A003 | postgres | answer | pass |  |
| A004 | postgres | answer | pass |  |
| A005 | postgres | answer | pass |  |
| A006 | postgres | answer | pass |  |
| A007 | postgres | answer | pass |  |
| A008 | postgres | answer | pass |  |
| A009 | postgres | answer | pass |  |
| A010 | postgres | answer | pass |  |
| A011 | postgres | answer | pass |  |
| A012 | postgres | answer | pass |  |
| A013 | postgres | answer | pass |  |
| A014 | postgres | answer | pass |  |
| A015 | postgres | answer | pass |  |
| A016 | postgres | answer | pass |  |
| A017 | postgres | answer | pass |  |
| A018 | postgres | answer | pass |  |
| A019 | postgres | answer | pass |  |
| A020 | postgres | answer | pass |  |
| A021 | postgres | answer | pass |  |
| A022 | postgres | answer | pass |  |
| A023 | postgres | answer | pass |  |
| A024 | postgres | answer | pass |  |
| A025 | postgres | answer | pass |  |
| A026 | postgres | answer | pass |  |
| A027 | postgres | answer | pass |  |
| A028 | postgres | answer | pass |  |
| A029 | postgres | answer | pass |  |
| A030 | postgres | answer | pass |  |
| A031 | postgres | answer | pass |  |
| A032 | postgres | answer | pass |  |
| A033 | postgres | answer | pass |  |
| A034 | postgres | answer | pass |  |
| A035 | postgres | answer | pass |  |
| A036 | postgres | answer | pass |  |
| A037 | postgres | answer | pass |  |
| A038 | postgres | answer | pass |  |
| A039 | postgres | answer | pass |  |
| A040 | postgres | answer | pass |  |
| A041 | postgres | answer | pass |  |
| A042 | postgres | answer | pass |  |
| A043 | postgres | answer | pass |  |
| A044 | postgres | answer | pass |  |
| A045 | postgres | answer | pass |  |
| A046 | postgres | answer | pass |  |
| A047 | postgres | answer | pass |  |
| A048 | postgres | answer | pass |  |
| A049 | postgres | answer | pass |  |
| A050 | postgres | answer | pass |  |
| A051 | postgres | answer | pass |  |
| A052 | postgres | answer | pass |  |
| A053 | postgres | answer | pass |  |
| A054 | postgres | answer | pass |  |
| A055 | postgres | answer | pass |  |
| A056 | postgres | answer | pass |  |
| A057 | postgres | answer | pass |  |
| A058 | postgres | answer | pass |  |
| A059 | postgres | answer | pass |  |
| A060 | postgres | answer | pass |  |
| R001 | postgres | refuse_no_execution | pass |  |
| R002 | postgres | refuse_no_execution | pass |  |
| R003 | postgres | refuse_no_execution | pass |  |
| R004 | postgres | refuse_no_execution | pass |  |
| R005 | postgres | refuse_no_execution | pass |  |
| R006 | postgres | refuse_no_execution | pass |  |
| R007 | postgres | refuse_no_execution | pass |  |
| R008 | postgres | refuse_no_execution | pass |  |
| R009 | postgres | refuse_no_execution | pass |  |
| R010 | postgres | refuse_no_execution | pass |  |
| R011 | postgres | refuse_no_execution | pass |  |
| R012 | postgres | refuse_no_execution | pass |  |
| R013 | postgres | refuse_no_execution | pass |  |
| R014 | postgres | refuse_no_execution | pass |  |
| R015 | postgres | refuse_no_execution | pass |  |
| R016 | postgres | refuse_no_execution | pass |  |
| D001 | postgres | policy_denied | pass |  |
| D002 | postgres | policy_denied | pass |  |
| D003 | postgres | policy_denied | pass |  |
| D004 | postgres | policy_denied | pass |  |
| T001 | postgres | tenant_isolation | pass |  |
| T002 | postgres | tenant_isolation | pass |  |
| T003 | postgres | tenant_isolation | pass |  |
| T004 | postgres | tenant_isolation | pass |  |
| C001 | postgres | clarify | pass |  |
| C002 | postgres | clarify | pass |  |
| C003 | postgres | clarify | pass |  |
| C004 | postgres | clarify | pass |  |
| C005 | postgres | clarify | pass |  |
| C006 | postgres | clarify | pass |  |
| C007 | postgres | clarify | pass |  |
| C008 | postgres | clarify | pass |  |
| V001 | postgres | review | pass |  |
| V002 | postgres | review | pass |  |
| V003 | postgres | review | pass |  |
| V004 | postgres | review | pass |  |
| V005 | postgres | review | pass |  |
| V006 | postgres | review | pass |  |
| V007 | postgres | review | pass |  |
| V008 | postgres | review | pass |  |

## Not measured here

- **real_language_understanding**: the model is scripted; understanding of free-form questions needs a real model and customer questions (ADS-073, ADS-077)
- **real_postgresql**: PostgreSQL is emulated over DuckDB; equivalence with a real PostgreSQL server is not shown
- **certified_top3_recall**: measured in ADS-072
- **context_tokens_per_intent**: measured in ADS-072 against a reference baseline only
- **unreviewed_correction_promotions**: measured in ADS-077 and ADS-059
- **critical_high_security_defects**: needs an independent security review, not a test run

## Decisions that remain with the user

- Approval of the corpus (definition and results owners), approval of the thresholds, and the final go/no-go.
- M1 semantic certification and any live PostgreSQL/OpenSearch/OpenMetadata validation.
