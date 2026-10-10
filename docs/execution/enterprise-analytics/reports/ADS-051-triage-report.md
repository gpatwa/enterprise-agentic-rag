# ADS-051: Triage Corpus Report

Generated 2026-10-10 04:55 UTC by `make analytics-triage-eval`. Corpus `triage-corpus-v1` (`8445a9fa86c7`), rules `triage-rules-v1`.

**Result: MEETS the approved thresholds.** The thresholds were approved by user on 2026-10-09 (scope: these triage-corpus thresholds only). This is not a gate pass for any human gate.

## Scope and limits

- Deterministic rules checked against labels written by hand from the rule definitions, on runs from the fakes-only reference stack.
- It shows the rules behave as specified and that notes cannot steer them. It says nothing about triage quality on real feedback.

## Metrics against approved thresholds

| Metric | Measured | Gate | Meets |
|---|---:|---:|:---:|
| `category_agreement` | 1 | >= 1.0 | yes |
| `rule_agreement` | 1 | >= 1.0 | yes |
| `determinism` | 1 | >= 1.0 | yes |
| `undetermined_lists_candidates` | 1 | >= 1.0 | yes |
| `note_independence` | 1 | >= 1.0 | yes |
| `claim_only_over_failed_runs` | 0 | <= 0 | yes |
| `record_mutations` | 0 | <= 0 | yes |

## Cases

| Case | Scenario | Expected | Got | Result |
|---|---|---|---|:---:|
| X01 | answer | none / T-00 / none / conflict=False | none / T-00 / none / conflict=False | pass |
| X02 | answer | semantic / T-91 / both / conflict=False | semantic / T-91 / both / conflict=False | pass |
| X03 | answer_omit_status | retrieval / T-90 / both / conflict=False | retrieval / T-90 / both / conflict=False | pass |
| X04 | answer | undetermined / T-92 / both / conflict=False | undetermined / T-92 / both / conflict=False | pass |
| X05 | answer | undetermined / T-95 / reporter_claim / conflict=False | undetermined / T-95 / reporter_claim / conflict=False | pass |
| X06 | answer | prose / T-60 / both / conflict=False | prose / T-60 / both / conflict=False | pass |
| X07 | answer | policy / T-70 / reporter_claim / conflict=False | policy / T-70 / reporter_claim / conflict=False | pass |
| X08 | answer | undetermined / T-85 / reporter_claim / conflict=False | undetermined / T-85 / reporter_claim / conflict=False | pass |
| X09 | answer | undetermined / T-81 / both / conflict=True | undetermined / T-81 / both / conflict=True | pass |
| X10 | policy_denied | policy / T-10 / system_evidence / conflict=True | policy / T-10 / system_evidence / conflict=True | pass |
| X11 | policy_denied | policy / T-10 / system_evidence / conflict=False | policy / T-10 / system_evidence / conflict=False | pass |
| X12 | unsupported_question | intent / T-20 / system_evidence / conflict=False | intent / T-20 / system_evidence / conflict=False | pass |
| X13 | unsupported_question | intent / T-20 / system_evidence / conflict=True | intent / T-20 / system_evidence / conflict=True | pass |
| X14 | clarification_exhausted | ontology / T-30 / system_evidence / conflict=False | ontology / T-30 / system_evidence / conflict=False | pass |
| X15 | cost_budget | execution / T-40 / system_evidence / conflict=True | execution / T-40 / system_evidence / conflict=True | pass |
| X16 | cost_budget | execution / T-40 / system_evidence / conflict=False | execution / T-40 / system_evidence / conflict=False | pass |
| X17 | answer | undetermined / T-95 / reporter_claim / conflict=False | undetermined / T-95 / reporter_claim / conflict=False | pass |
| X18 | policy_denied | policy / T-10 / system_evidence / conflict=True | policy / T-10 / system_evidence / conflict=True | pass |

## Not measured

- **real_feedback_quality**: needs real user feedback and independent labelling; not available at M5 start
