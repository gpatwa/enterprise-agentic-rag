# ADS-055: Independent Review Report

Generated 2026-10-10 07:12 UTC by `make analytics-review-eval`. Corpus `review-corpus-v1` (`ad45335a620f`), rules `review-rules-v1`.

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. This is not the M5 `separation_of_duties_review` approval; approving a subject applies, certifies, and promotes nothing.

## Scope and limits

- Reviewers are reference-stack tokens with a group claim; there is no real identity provider or group sync.
- Each case runs in a fresh fakes-only stack with hand-written expectations; they show the rules behave as specified.

## Metrics against proposed thresholds

| Metric | Measured | Gate | Meets |
|---|---:|---:|:---:|
| `outcome_agreement` | 1 | >= 1.0 | yes |
| `forbidden_decision_rejection` | 1 | >= 1.0 | yes |
| `stale_decision_rejection` | 1 | >= 1.0 | yes |
| `expiry_enforcement` | 1 | >= 1.0 | yes |
| `audit_completeness` | 1 | >= 1.0 | yes |
| `approvals_without_independent_review` | 0 | <= 0 | yes |
| `subject_mutations` | 0 | <= 0 | yes |
| `determinism` | 1 | >= 1.0 | yes |
| `protected_file_writes` | 0 | <= 0 | yes |

## Cases

| Case | Operation | Expected | Got | Result |
|---|---|---|---|:---:|
| W01 | approve_independent | approved | approved | pass |
| W02 | generator_decides | refused:automated_identity | refused:automated_identity | pass |
| W03 | model_decides | refused:automated_identity | refused:automated_identity | pass |
| W04 | feedback_submitter_decides | refused:is_contributor | refused:is_contributor | pass |
| W05 | requester_decides | refused:is_requester | refused:is_requester | pass |
| W06 | non_reviewer_decides | refused:not_a_reviewer | refused:not_a_reviewer | pass |
| W07 | other_tenant_decides | refused:review_not_found | refused:review_not_found | pass |
| W08 | purpose_not_authorized | refused:purpose_not_authorized | refused:purpose_not_authorized | pass |
| W09 | wrong_fingerprint | refused:fingerprint_mismatch | refused:fingerprint_mismatch | pass |
| W10 | subject_changed | refused:subject_changed | refused:subject_changed | pass |
| W11 | decide_after_expiry | refused:expired | refused:expired | pass |
| W12 | reject_then_approve | refused:review_closed | refused:review_closed | pass |
| W13 | double_decision | refused:already_decided_by_reviewer | refused:already_decided_by_reviewer | pass |
| W14 | two_approvals_required | approved | approved | pass |
| W15 | prompt_candidate_independent | approved | approved | pass |
| W16 | prompt_candidate_creator | refused:automated_identity | refused:automated_identity | pass |
| W17 | example_submitter_decides | refused:is_contributor | refused:is_contributor | pass |
| W18 | released_baseline | refused:not_reviewable | refused:not_reviewable | pass |
| W19 | pending_is_not_approved | pending | pending | pass |
| W20 | unknown_subject | refused:subject_not_found | refused:subject_not_found | pass |

## Not measured

- **identity_management**: reviewers are reference-stack tokens with a group claim; a real identity provider and group sync are later work
- **M5_gate**: approving a subject is not the M5 separation_of_duties_review human gate
