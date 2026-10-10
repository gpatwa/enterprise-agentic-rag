# ADS-052: Change Proposal Report

Generated 2026-10-10 06:30 UTC by `make analytics-proposals-eval`. Corpus `proposal-corpus-v1` (`3d609f357cc8`), rules `proposal-rules-v1`.

**Result: MEETS the approved thresholds.** The thresholds were approved by user on 2026-10-09 (scope: these proposal-corpus thresholds only). This is not a gate pass for any human gate and approves no proposal.

## Scope and limits

- Proposals are inert data (status `proposed`); nothing is applied, reviewed, or certified here (review is ADS-055).
- Expectations were written by hand from the rule definitions on the fakes-only reference stack. They show the rules behave as specified and are safe; they say nothing about whether proposals are good fixes.

## Metrics against approved thresholds

| Metric | Measured | Gate | Meets |
|---|---:|---:|:---:|
| `proposal_agreement` | 1 | >= 1.0 | yes |
| `provenance_completeness` | 1 | >= 1.0 | yes |
| `never_certified_violations` | 0 | <= 0 | yes |
| `draft_validity` | 1 | >= 1.0 | yes |
| `protected_file_writes` | 0 | <= 0 | yes |
| `determinism` | 1 | >= 1.0 | yes |
| `dedupe_agreement` | 1 | >= 1.0 | yes |

## Cases

| Case | Scenario | Expected | Got | Result |
|---|---|---|---|:---:|
| P01 | answer | {'operation': 'flag_definition_for_review', 'target_kind': 'metric', 'target_id': 'revenue'} | {'operation': 'flag_definition_for_review', 'target_kind': 'metric', 'target_id': 'revenue'} | pass |
| P02 | answer | {'operation': 'flag_definition_for_review', 'target_kind': 'metric', 'target_id': 'revenue'} | {'operation': 'flag_definition_for_review', 'target_kind': 'metric', 'target_id': 'revenue'} | pass |
| P03 | answer_omit_status | {'operation': 'add_context_edge', 'target_kind': 'dimension', 'target_id': 'status'} | {'operation': 'add_context_edge', 'target_kind': 'dimension', 'target_id': 'status'} | pass |
| P04 | clarification_exhausted | {'operation': 'review_label_collision', 'target_kind': 'ontology_label', 'target_id': 'time'} | {'operation': 'review_label_collision', 'target_kind': 'ontology_label', 'target_id': 'time'} | pass |
| P05 | answer | {'none': 'claim_only'} | {'none': 'claim_only'} | pass |
| P06 | answer | {'none': 'category_not_applicable'} | {'none': 'category_not_applicable'} | pass |
| P07 | policy_denied | {'none': 'category_not_applicable'} | {'none': 'category_not_applicable'} | pass |
| P08 | cost_budget | {'none': 'category_not_applicable'} | {'none': 'category_not_applicable'} | pass |
| P09 | unsupported_question | {'none': 'category_not_applicable'} | {'none': 'category_not_applicable'} | pass |
| P10 | answer | {'none': 'claim_only'} | {'none': 'claim_only'} | pass |
| P11 | answer | {'operation': 'flag_definition_for_review', 'target_kind': 'metric', 'target_id': 'revenue'} | {'operation': 'flag_definition_for_review', 'target_kind': 'metric', 'target_id': 'revenue'} | pass |

## Proposals generated

- `7019a70567b6` flag_definition_for_review on metric `revenue` (base sales-core@v1, status proposed)
- `f1c743c565c1` add_context_edge on dimension `status` (base sales-core@v1, status proposed)
- `dac62a737bb9` review_label_collision on ontology_label `time` (base sales-core@v1, status proposed)

## Not measured

- **proposal_usefulness**: needs reviewers and real feedback; reviewing proposals is ADS-055
