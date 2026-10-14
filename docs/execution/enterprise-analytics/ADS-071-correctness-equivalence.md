# ADS-071: End-to-End Correctness and PostgreSQL/DuckDB Equivalence

Status: **Review** (evaluated locally; thresholds and corpus are **proposed, not approved**)
Milestone: M7 (wave 7B)
Depends on: ADS-070

## Decisions made under the user's delegation ("make the decision")

1. **Reuse the M4 golden machinery on the ADS-070 corpus.** `golden.run_golden` now accepts a corpus and a thresholds file (M4 defaults unchanged), so the same checks
   (independent-oracle rows, evidence sealing, replay fingerprint, budget, raw-SQL accounting, dialect equivalence, latency) apply to 100 cases on both dialects.
2. **Gates are plan section 10, unchanged.** `m7/e2e-thresholds.proposed.json` copies the twelve measurable gates; it is pinned to the corpus digest and is **proposed**.
   The report states that both the thresholds and the corpus are unapproved, so a pass is not a go/no-go.
3. **Latency here is a smoke signal.** The plan says latency must be re-baselined for the staging model and warehouse; ADS-076 treats it properly.

## Deliverable

- `reference_stack/m7_eval.py::run_correctness`, `make analytics-m7-correctness`, report `reports/ADS-071-correctness-report.{md,json}`
- `reference_stack/m7/e2e-thresholds.proposed.json`, `tests/test_ads071_correctness.py`

## Evidence

200 case runs (100 cases x DuckDB and emulated PostgreSQL): all passed; all twelve proposed gates met (P0 and full-answer equivalence 100%, refusal recall 100%,
clarify/review 100%, zero policy/tenant violations, zero raw-model-SQL executions, evidence completeness 100%, replay equivalence 100%, dialect equivalence 100%).
Tests also show that a wrong expectation, a wrong dialect result, and a missed refusal each fail their gate.

## Boundary

- PostgreSQL is emulated; the scripted model recognises the corpus phrasings. This shows the governed pipeline is consistent, not that a real model or warehouse is.
- Owner approval of the corpus and thresholds, and the final go/no-go, are the user's.
