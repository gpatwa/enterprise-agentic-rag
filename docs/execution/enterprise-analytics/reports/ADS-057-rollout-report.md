# ADS-057: Rollout Report

Generated 2026-10-10 19:11 UTC by `make analytics-rollout-eval`. Corpus `rollout-corpus-v1` (`530321c05dad`), rules `rollout-rules-v1`.

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. This is not the M5 `separation_of_duties_review` approval. The rollout policy used here is a test-harness copy marked approved; the repository's policy remains proposed, so the controller will not promote anything until the user approves it.

## Scope and limits

- Observers are simulated: a pinned request set served through sandbox stacks, with injected faults. There is no live traffic.
- Promotion only creates the next released registry version and appends an active-version pointer; nothing in the runtime reads either.

## Metrics against proposed thresholds

| Metric | Measured | Gate | Meets |
|---|---:|---:|:---:|
| `outcome_agreement` | 1 | >= 1.0 | yes |
| `ungated_start_refusal` | 1 | >= 1.0 | yes |
| `bad_candidate_rollback` | 1 | >= 1.0 | yes |
| `pointer_integrity` | 1 | >= 1.0 | yes |
| `release_immutability` | 0 | <= 0 | yes |
| `evidence_preserved` | 1 | >= 1.0 | yes |
| `idempotency` | 1 | >= 1.0 | yes |
| `runtime_unwired` | 0 | <= 0 | yes |
| `protected_file_writes` | 0 | <= 0 | yes |

## Cases

| Case | Operation | Expected | Got | Result |
|---|---|---|---|:---:|
| K01 | happy_path | promoted:v2 | promoted:v2 | pass |
| K02 | no_review | refused:review_not_approved | refused:review_not_approved | pass |
| K03 | no_evaluation | refused:evaluation_not_passed | refused:evaluation_not_passed | pass |
| K04 | harmful_candidate | refused:evaluation_not_passed | refused:evaluation_not_passed | pass |
| K05 | repository_policy_not_approved | refused:rollout_policy_not_approved | refused:rollout_policy_not_approved | pass |
| K06 | automated_starter | refused:automated_identity | refused:automated_identity | pass |
| K07 | shadow_fault | rolled_back:shadow_disagreement | rolled_back:shadow_disagreement | pass |
| K08 | canary_fault | rolled_back:canary_regression:0.5 | rolled_back:canary_regression:0.5 | pass |
| K09 | monitor_fault | rolled_back:monitor_regression | rolled_back:monitor_regression | pass |
| K10 | stale_approval | rolled_back:gate_lost:approval_stale | rolled_back:gate_lost:approval_stale | pass |
| K11 | skip_canary | refused:canary_incomplete | refused:canary_incomplete | pass |
| K12 | double_promote | promoted:v2 | promoted:v2 | pass |

## Not measured

- **live_traffic**: shadow, canary, and monitor use a pinned request set served through sandbox stacks, not production traffic
- **runtime_wiring**: nothing reads the promoted version or the active pointer; wiring the runtime to the registry needs its own separately approved step
