# ADS-058: Drift Monitor Report

Generated 2026-10-13 01:06 UTC by `make analytics-drift-eval`. Corpus `drift-corpus-v1` (`3fc910dadfaf`), rules `drift-rules-v1`, alert policy `drift-policy-v1` (**proposed**).

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. This is not the M5 `separation_of_duties_review` approval. The alert thresholds in the drift policy are also proposed: they were chosen without production data.

## Scope and limits

- Windows are synthetic and deterministic; the one real run only proves extraction works. There is no production traffic.
- Monitors are advisory and read-only. An alert starts no rollback and changes no run, release, pointer, or threshold.

## Metrics against proposed thresholds

| Metric | Measured | Gate | Meets |
|---|---:|---:|:---:|
| `case_agreement` | 1 | >= 1.0 | yes |
| `drift_recall` | 1 | >= 1.0 | yes |
| `false_alerts` | 0 | <= 0 | yes |
| `runbook_coverage` | 1 | >= 1.0 | yes |
| `insufficient_data_silence` | 1 | >= 1.0 | yes |
| `quiet_window_silence` | 1 | >= 1.0 | yes |
| `real_run_extraction` | 1 | >= 1.0 | yes |
| `monitor_writes` | 0 | <= 0 | yes |
| `runtime_unwired` | 0 | <= 0 | yes |
| `protected_file_writes` | 0 | <= 0 | yes |

## Cases

| Case | Name | Expected alerts | Got | Skipped rules | Result |
|---|---|---|---|---:|:---:|
| D01 | stable_with_noise | none | none | 0 | pass |
| D02 | stale_context | C-01 | C-01 | 0 | pass |
| D03 | context_age | C-02 | C-02 | 0 | pass |
| D04 | empty_retrieval | R-01 | R-01 | 0 | pass |
| D05 | retrieval_items_drop | R-02 | R-02 | 0 | pass |
| D06 | malformed_intent | I-01 | I-01 | 0 | pass |
| D07 | clarification_surge | I-02 | I-02 | 0 | pass |
| D08 | outcome_mix_shift | O-01 | O-01 | 0 | pass |
| D09 | success_rate_drop | O-02 | O-02 | 0 | pass |
| D10 | latency_regression | L-01 | L-01 | 0 | pass |
| D11 | cost_regression | K-01 | K-01 | 0 | pass |
| D12 | latency_and_cost | K-01,L-01 | K-01,L-01 | 0 | pass |
| D13 | insufficient_data | none | none | 10 | pass |
| D14 | just_below_thresholds | none | none | 0 | pass |
| D15 | latency_exactly_at_threshold | L-01 | L-01 | 0 | pass |
| D16 | stale_exactly_at_threshold | C-01 | C-01 | 0 | pass |
| D17 | improvement_is_not_drift | none | none | 0 | pass |
| D18 | zero_baseline_cost | none | none | 1 | pass |

## Not measured

- **production_traffic**: windows are synthetic; real alert precision, recall, and the right thresholds need production data
- **alert_delivery**: alerts go to an in-memory sink; paging, dashboards, and on-call routing are not built
- **automatic_response**: an alert never triggers a rollback or any action; a person follows the runbook
