# ADS-077: Model/Provider Variance, Degraded-Mode, and Rollback Evaluation

Status: **Review** (local; scripted providers; thresholds **proposed, not approved**)
Milestone: M7 (wave 7B)
Depends on: ADS-057, ADS-070

## Decisions made under the user's delegation ("make the decision")

1. **Providers are scripted distortions of the scripted model**: equivalent wire formats (reordered keys, JSON string, pretty-printed string), non-conforming output (extra field, markdown fence,
   truncated JSON, wrong type, empty reply, a first-call timeout), a changed label case, and a provider that is down. Six questions each, through the whole pipeline.
2. **Gates:** no wrong answers; equivalent formats give identical result fingerprints; non-conforming output and a down provider end in a typed failure (`planner_unavailable`) with no query run and
   **one model call** (no retry storm); ungrounded explainer claims never reach the caller (`evidence_only`, rows still correct); pinned prompt versions reproduce, including after a rollback to the first prompt.
3. **Rollout and poisoning evidence is folded in.** The ADS-057 rollout corpus (bad-candidate rollback, pointer integrity) and ADS-059 poisoning corpus (the plan's "unreviewed correction promotions 0") are re-run.
4. **A changed label case is not a failure.** The certified ontology resolves labels case-insensitively by design (ADS-034); it may answer, and must never answer wrongly.

## Deliverable

- `reference_stack/provider_eval.py`, `m7/provider-thresholds.proposed.json`, `make analytics-m7-provider`, report `reports/ADS-077-provider-report.{md,json}`, `tests/test_ads077_provider.py`

## Boundary

- Real provider behaviour (limits, safety refusals, streams, rate limits, silent updates) is not modelled. A well-formed intent for the wrong question is still answered (no intent-echo check; see ADS-073).
- There is no retry and no circuit breaker: failure is bounded, but a flaky provider is never retried automatically. The runtime does not read the prompt registry or rollout pointer, so rollback is evaluated on the controller and pinned templates.
