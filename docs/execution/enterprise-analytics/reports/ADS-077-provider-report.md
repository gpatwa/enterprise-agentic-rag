# ADS-077: Model/Provider Variance, Degraded-Mode, and Rollback Evaluation

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. The providers are scripted distortions of one scripted model: **this shows the pipeline's bounds, not how a real provider behaves.**

66 provider runs over 11 behaviours, a provider-down run of 12 requests (0.6 s, codes ['planner_unavailable']), 3 explainer failures, and 4 prompt-version comparisons over 6 questions.

## Metrics

| Metric | Measured | Gate | Meets | Plan gate |
|---|---:|---:|:---:|---|
| `provider_wrong_answers` | 0 | <= 0 | yes | A provider's output yields rows that differ from the oracle: 0 |
| `equivalent_provider_agreement` | 1 | >= 1.0 | yes | The same intent in a different wire format gives the same result fingerprint: 100% |
| `nonconforming_provider_safe_rate` | 1 | >= 1.0 | yes | A non-conforming provider output ends in a typed failure with no query run: 100% |
| `model_calls_per_failing_run_max` | 1 | <= 1 | yes | Provider failure is bounded: no retry storm (calls per failing run) |
| `degraded_mode_unsafe_outcomes` | 0 | <= 0 | yes | With the provider down, every request ends in a typed failure with no query run: 0 exceptions |
| `ungrounded_claims_shown` | 0 | <= 0 | yes | An ungrounded explainer's claims reach the caller: 0 |
| `prompt_version_reproducibility` | 1 | >= 1.0 | yes | The same pinned prompt gives identical result fingerprints on re-run, and after a rollback: 100% |
| `rollout_and_rollback_gates_met` | 1 | >= 1.0 | yes | ADS-057 rollout gates (including bad-candidate rollback) met |
| `unreviewed_correction_promotions` | 0 | <= 0 | yes | Unreviewed correction promotions: 0 (ADS-059 gates met) |

## Explainer degradation

| Case | Outcome | Explanation status | Claims shown | Rows correct |
|---|---|---|---:|:---:|
| ungrounded_number | answer | evidence_only | 0 | yes |
| uncited_claim | answer | evidence_only | 0 | yes |
| claim_cites_nothing_real | answer | evidence_only | 0 | yes |

## Provider behaviours

| Behaviour | Outcomes (6 questions) |
|---|---|
| baseline | answer:ok |
| reordered_keys | answer:ok |
| json_string | answer:ok |
| pretty_json_string | answer:ok |
| extra_field | failed |
| markdown_fence | failed |
| truncated_json | failed |
| wrong_type | failed |
| empty_reply | failed |
| flaky_first_call | failed |
| uppercase_metric | answer:ok, failed |

## Not measured

- **real_provider_behaviour**: real providers differ in ways not modelled here: token limits, safety refusals, partial streams, rate limits, latency tails, silent model updates
- **valid_but_wrong_intent**: a well-formed intent for the wrong question (for example a status breakdown for a monthly question) is answered; no intent-echo check exists (open gap from ADS-073)
- **prompt_effect**: the scripted model ignores prompt text, so reproducibility across prompt versions shows the pipeline adds no nondeterminism, not that a prompt change leaves a real model's behaviour unchanged
- **runtime_wiring**: the runtime does not read the prompt registry or rollout pointer; rollback is evaluated on the rollout controller (ADS-057) and pinned prompt templates, not on a live pointer
- **retry_and_circuit_breaking**: there is no retry and no circuit breaker: each run makes one model call and fails, which bounds a failure but means a flaky provider is never retried automatically
