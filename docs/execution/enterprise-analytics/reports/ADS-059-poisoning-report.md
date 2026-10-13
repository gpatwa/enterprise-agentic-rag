# ADS-059: Closed-Loop Safety and Poisoning Report

Generated 2026-10-13 01:13 UTC by `make analytics-poisoning-eval`. Corpus `poisoning-corpus-v1` (`08a7e7e088dd`), rules `poisoning-rules-v1`.

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. This is not the M5 `separation_of_duties_review` approval, and it is not an independent review of the pipeline's code.

## Scope and limits

- The cases run the real ADS-050 to ADS-057 code on the reference stack with fakes only; there is no live system, no real model, and no production traffic.
- Expected outcomes are hand-written from the rules. The corpus covers the attacks its author thought of; it is a regression net, not a proof of safety.
- Case X23 assumes an independent reviewer approved a harmful candidate (a compromised reviewer): the control that stops it is the evaluation gate, not the review.

## Metrics against proposed thresholds

| Metric | Measured | Gate | Meets |
|---|---:|---:|:---:|
| `case_agreement` | 1 | >= 1.0 | yes |
| `intake_block_rate` | 1 | >= 1.0 | yes |
| `contract_block_rate` | 1 | >= 1.0 | yes |
| `approval_block_rate` | 1 | >= 1.0 | yes |
| `barred_approvals` | 0 | <= 0 | yes |
| `free_text_inert` | 1 | >= 1.0 | yes |
| `flood_amplification` | 1 | <= 1 | yes |
| `production_answer_unchanged` | 1 | >= 1.0 | yes |
| `golden_thresholds_still_met` | 1 | >= 1.0 | yes |
| `release_mutations` | 0 | <= 0 | yes |
| `pipeline_wired_into_runtime` | 0 | <= 0 | yes |
| `protected_file_writes` | 0 | <= 0 | yes |

## Cases

| Case | Name | Group | Expected | Got | Result |
|---|---|---|---|---|:---:|
| X01 | sql_in_correction | intake | rejected | rejected | pass |
| X02 | unknown_metric | intake | rejected | rejected | pass |
| X03 | wrong_kind_of_id | intake | rejected | rejected | pass |
| X04 | extra_sql_field | intake | rejected | rejected | pass |
| X05 | oversized_note | intake | rejected | rejected | pass |
| X06 | correct_verdict_with_correction | intake | rejected | rejected | pass |
| X07 | foreign_tenant_submitter | intake | rejected | rejected | pass |
| X08 | missing_idempotency_key | intake | rejected | rejected | pass |
| X09 | injection_in_free_text_note | free_text | inert | inert | pass |
| X10 | feedback_flood | volume | flood:proposals=1:approved_reviews=0 | flood:proposals=1:approved_reviews=0 | pass |
| X11 | weakened_defensive_clauses | contract | rejected | rejected | pass |
| X12 | patch_certifies_a_contract | contract | rejected | rejected | pass |
| X13 | patch_rewrites_a_definition | contract | rejected | rejected | pass |
| X14 | patch_touches_policy | contract | rejected | rejected | pass |
| X15 | dbt_edit_of_project_file | contract | rejected | rejected | pass |
| X16 | dbt_edit_path_traversal | contract | rejected | rejected | pass |
| X17 | dbt_multiline_description | contract | rejected | rejected | pass |
| X18 | example_from_unsafe_verdict | contract | rejected | rejected | pass |
| X19 | contributor_approves_own_candidate | approval | refused:is_contributor | refused:is_contributor | pass |
| X20 | automated_identity_approves | approval | refused:automated_identity | refused:automated_identity | pass |
| X21 | requester_approves_own_request | approval | refused:is_requester | refused:is_requester | pass |
| X22 | non_reviewer_approves | approval | refused:not_a_reviewer | refused:not_a_reviewer | pass |
| X23 | harmful_candidate_approved_by_a_reviewer | chain | refused:evaluation_not_passed | refused:evaluation_not_passed | pass |
| X24 | unreviewed_candidate | chain | refused:review_not_approved | refused:review_not_approved | pass |
| X25 | rollout_without_an_approved_policy | chain | refused:rollout_policy_not_approved | refused:rollout_policy_not_approved | pass |
| X26 | automated_starter | chain | refused:automated_identity | refused:automated_identity | pass |

## Not measured

- **unlisted_attacks**: the corpus holds the attacks its author thought of; novel attacks, collusion between two real reviewers, and compromised infrastructure are out of scope
- **live_systems**: no live model, warehouse, OpenSearch, or identity provider; tokens come from the reference stack's test issuer
- **independent_review**: this evaluation is not an independent review of the pipeline's code or the M5 separation_of_duties_review
