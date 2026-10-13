# M7 pending decisions: persona recommendations (NOT approvals)

Status: **Recommendations only.** Written by the implementing agent speaking as each role. Nothing here is an approval, a sign-off, or an independent review, and none of it is recorded in the program manifest. A person must adopt, amend, or reject each item in their own words before it counts.

## Engineering lead

| Decision | Recommendation | Reason |
|---|---|---|
| Proposed thresholds (ADS-054..059, 066, 067, 068, 071..078) | Approve the correctness, security, and isolation gates as written (plan section 10; zero-violation gates). Approve latency/cost gates only as "smoke" gates until re-baselined on the staging model and warehouse. | Correctness and security gates must not be relaxed for infrastructure limits; latency and cost numbers are meaningless on a scripted model. |
| `answers_per_tenant_day` (92 < 100) | Calibrate the estimator's cost units against the real warehouse first; do not raise the 10,000 budget until then. | The units vary 25 to 263 by query; raising the budget would hide an uncalibrated measure. |
| Process-crash recovery | Build durable compiled-plan and result storage (or re-plan on resume) before any pilot. | 10 of 26 crash points fail closed today; safe, but a real outage would fail in-flight runs. |
| Intent-echo check (ADS-073 gap) | Add a deterministic check that the extracted intent's metric and dimensions are supported by the question's resolved terms, before any real model is used. | The scripted model answered 4 of 4 near-miss questions; a real model needs this backstop. |
| Retry guidance | Document that a failed run needs a new idempotency key; add a typed `retry_with_new_key` hint. | Same key returns the same failure. |
| Ossie export | Carry metrics and time-dimension flags in the export. | Does not change the Compass schema; makes round trips lossless. |
| Independent review of ADS-040+ | Assign engineers who did not write the code; start with ADS-040 to 049 (the local-demo scope). | The author cannot review their own work. |

## Security lead

| Decision | Recommendation |
|---|---|
| F-02 (derivable run IDs) | Make `run_id_key` a mandatory deployment setting; refuse to start without it outside tests. |
| F-03 (small cohorts / differencing) | Set `min_cohort` (suggest 10 as a starting point, to be tuned with the data owner) before any personal-data dataset is onboarded. |
| F-05 (same-tenant, same-purpose readers) | Decide whether run visibility should be requester-only or group-based; recommend requester plus named reviewers. |
| Automated actors | Enforce the `agent:`/`service:` id-prefix convention at the identity provider. |
| M0 / M5 / M6 gates | Withhold until an independent security review of ADS-060 to 068 is done. |

## Data owner and product owner

| Decision | Recommendation |
|---|---|
| Reference corpus | Replace the 30 "customer-style" phrasings with 25 to 50 real questions; then each of the definition owner and results owner approves separately. |
| M1 semantic certification | Certify only after owners review the imported ownership, grain, and metric definitions. |
| Onboarding | Human-authored policies are mandatory; never certify an Ossie import as-is. |

## Operations lead

| Decision | Recommendation |
|---|---|
| Runbooks | Walk the 11 `ops-*` runbooks in a game day with a person who did not write them. |
| Live validation | Authorize PostgreSQL, OpenSearch, and IdP validation in a staging environment as a separate, explicit request. |
| Deployment checklist | Treat `ops-deployment-checklist` as a release gate. |

## Final go/no-go

Recommendation from the evidence: **no-go for a pilot today.** The blockers are in `reports/ADS-079-evidence-manifest.md`. Reconsider after: real model and warehouse are selected and the latency/cost gates re-baselined; thresholds and corpus are approved by named people; independent reviews and the five human gates are recorded; F-02, F-03, F-05 are resolved or formally accepted.

## Progress after the user's instructions

- The user wrote "I approved M0/M1/M5/M6/M7 gates"; that is recorded in the program manifest in their words and only for those five gates. No threshold or policy file, corpus, sign-off, or independent review was approved by it.
- Built from the engineering recommendations: Ossie export carries metrics and time dimensions; durable plan and policy-value storage (M7-H1); the intent-echo check (M7-H2); retry guidance (M7-H3); the cost-calibration mechanism (M7-H4). See `M7-hardening.md`.
- Not done: cost-unit calibration against a real warehouse (needs real samples and a person's approval).
