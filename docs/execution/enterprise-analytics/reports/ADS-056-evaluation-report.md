# ADS-056: Candidate Evaluation Report

Generated 2026-10-10 18:51 UTC by `make analytics-evaluation-eval`. Corpus `evaluation-corpus-v1` (`b440fcd8a4ae`), rules `evaluation-rules-v1`.

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. This is not the M5 `separation_of_duties_review` approval; an evaluation promotes, certifies, and releases nothing.

## Scope and limits

- Candidates are applied only in sandbox stacks (a prompt for the intent node, or review flags on a contract copy); nothing is written to the registry, runtime, or any protected file.
- The model is scripted and keyword-driven, so this shows the gate catches regressions in the pinned suites, not that a prompt is better.

## Metrics against proposed thresholds

| Metric | Measured | Gate | Meets |
|---|---:|---:|:---:|
| `verdict_agreement` | 1 | >= 1.0 | yes |
| `harmful_candidate_detection` | 1 | >= 1.0 | yes |
| `unreviewed_evaluation_refusal` | 1 | >= 1.0 | yes |
| `selection_agreement` | 1 | >= 1.0 | yes |
| `full_suite_coverage` | 1 | >= 1.0 | yes |
| `approved_threshold_only` | 1 | >= 1.0 | yes |
| `fail_closed` | 1 | >= 1.0 | yes |
| `protected_file_writes` | 0 | <= 0 | yes |
| `determinism` | 1 | >= 1.0 | yes |

## Cases

| Case | Operation | Expected | Got | Result |
|---|---|---|---|:---:|
| E01 | harmless_prompt | passed | passed | pass |
| E02 | harmful_prompt | failed:suite_failed:golden | failed:suite_failed:golden | pass |
| E03 | flag_proposal | passed | passed | pass |
| E04 | context_edge_proposal | passed | passed | pass |
| E05 | dbt_description_proposal | passed | passed | pass |
| E06 | unreviewed_prompt | refused:review_not_approved | refused:review_not_approved | pass |
| E07 | rejected_prompt | refused:review_not_approved | refused:review_not_approved | pass |
| E08 | tampered_protected_file | failed:protected_file_changed | failed:protected_file_changed | pass |
| E09 | unapproved_thresholds | failed:unapproved_thresholds | failed:unapproved_thresholds | pass |
| S01 | select | ['A01', 'G01', 'G02', 'G03', 'G04', 'G05', 'G06', 'P01', 'R01', 'R02', 'R03', 'R04', 'V01'] | ['A01', 'G01', 'G02', 'G03', 'G04', 'G05', 'G06', 'P01', 'R01', 'R02', 'R03', 'R04', 'V01'] | pass |
| S02 | select | ['G01', 'G02', 'G03', 'G04', 'G05', 'G06', 'P01', 'V01'] | ['G01', 'G02', 'G03', 'G04', 'G05', 'G06', 'P01', 'V01'] | pass |
| S03 | select | ['A01', 'G02', 'G04', 'G06'] | ['A01', 'G02', 'G04', 'G06'] | pass |
| S04 | select | ['A01', 'G01', 'G02', 'G04', 'G05', 'G06', 'V01'] | ['A01', 'G01', 'G02', 'G04', 'G05', 'G06', 'V01'] | pass |
| S05 | select | ['G01', 'G02', 'G03', 'G04', 'G05', 'G06', 'P01', 'V01'] | ['G01', 'G02', 'G03', 'G04', 'G05', 'G06', 'P01', 'V01'] | pass |

## Not measured

- **candidate_quality**: the scripted model ignores instruction text before the request, so a prompt's real effect on answers is not measured
- **live_traffic**: shadow and canary behaviour belongs to ADS-057
