Status: AI persona advisory review (product owner). Not an approval or human sign-off.

Reviewer persona: product owner for an enterprise natural-language analytics product, deciding the quality bar for a limited pilot.
Written 2026-10-15 against branch `claude/persona-reviews` (base `27663d6`). Read-only review: no code, config, threshold, corpus, or manifest was changed, and no evaluation was re-run for this review. Every number quoted below comes from the committed reports.

## Summary

- **Verdict: no-go for a pilot today. This agrees with `M7-decision-recommendations.md` and the ADS-079 manifest (`pending_human_review`).** The governed pipeline is well built and fails closed. Its safety properties hold up under adversarial testing on fakes. But no test has measured what a pilot user actually experiences, which is how often a real model, on real questions, against a real warehouse, gives a right answer, a wrong answer, an unnecessary refusal, or a clarification. Every correctness, abstention, and provider gate passes on a **scripted keyword model** that recognises the corpus phrasings by construction.
- **What pilot users will care about most, in order:**
  1. Never get a confidently wrong number.
  2. Get an answer to most in-scope questions.
  3. When not answered, understand why and what to do next.
  4. Get answers in a tolerable time.

  The current gates cover (1) well on the mechanism side. They cannot measure (2) yet. The UX for (3) is the weakest part of the product as built.
- **The thresholds are mostly right in spirit.** I recommend approving the zero-tolerance safety gates as written. I recommend amending the e2e correctness gate so the 5% slack can only be spent on refusals and clarifications, never on wrong rows. I recommend treating latency, cost, quota, drift, and rollout numbers as placeholders until they are re-measured on staging. I recommend rejecting the reference corpus as a *pilot* corpus until it has real customer questions.
- **Outcome UX needs a copy and routing pass before any pilot.** Users will see raw codes (`metric not in question:revenue`, `cost_threshold`, raw candidate IDs as clarification buttons). An expired review is reported as `stale_metadata`. A reviewer's rejection is reported as "refused by policy or review". A requester sees an enabled Approve button they are not allowed to use. A context-search outage is shown as a refusal rather than a retryable failure.
- **Records need a human to reconcile them.** The program manifest records `M7: final_go_no_go = approved` (from the user's 2026-10-13 message), but ADS-079 lists six open blockers and no signatures. That gate approval must not be read as a pilot go decision; see Questions.

## Threshold recommendations

How to read this table:

- **Scripted?** means the gate passes because the model's output is scripted or chosen, so passing says little about a real model.
- **Mechanism** means a deterministic property of the code. These pass legitimately, and a real model would not change them.
- **"Approve"** here is my *advice* to the human owner. It is not an approval.

| File | Recommendation | Exact values / changes | User-perspective rationale | Scripted? |
|---|---|---|---|---|
| `m7/e2e-thresholds.proposed.json` | **Amend** | Keep every plan section 10 value. **Add** `wrong_answer_rate_answered` <= 0 for P0 cases and <= 0.01 over all answered cases: the share of answered cases whose rows differ from the oracle. **Add** `answer_coverage` >= 0.85 over in-scope answer cases (staging, real model). Re-label `p95_answer_latency_seconds` <= 8.0 as "local smoke". Add a staging gate: `p95_answer_latency_seconds_staging` <= 15.0 and `p50` <= 6.0 with the real model and warehouse. | As written, `answer_result_equivalence >= 0.95` would allow 5% of answers to be *wrong*. Users forgive "I can't answer that" far more readily than a wrong revenue number. The slack must be spent on abstention, not on errors. 8 s P95 on a 100-row DuckDB says nothing; a real LLM call dominates. | **Yes** for equivalence, refusal, and clarify recall (keyword model, 600 answered calls). Mechanism for raw-SQL, evidence, replay, and budget gates. |
| `m7/abstention-thresholds.proposed.json` | **Amend** | Keep `abstention_recall` 1.0, `guess_rate` 0, `near_miss_answered` 0, `executed_queries_on_abstention` 0, `uncalibrated_confidence_claims` 0, and `clarify_recall` 0.95. Change `false_abstention_rate` <= 0.05 to **two gates**: <= 0.05 on the reference corpus (regression), and <= 0.15 on the owner-approved real-question set with the real model (pilot). Grow the near-miss set from 4 or 8 cases to >= 25, written by the data owner. | The lexical intent-echo check (M7-H2) will refuse unusual phrasings of valid questions. During a pilot I would rather over-refuse than mis-answer, but above about 15% users will give up. 4 near-miss cases is far too few to trust a 0 rate. | **Yes**: outputs are chosen per case, and the echo check was tuned against these same phrasings. |
| `m7/retrieval-thresholds.proposed.json` | **Approve values, require re-run** | Values unchanged (top-3 >= 0.98, 0 foreign or uncertified results, 100% provenance and stale detection, -20% tokens, 0 overruns). Pilot condition: re-run on a live OpenSearch index with the pilot catalogue and real question wording. | Retrieval misses surface to users as needless refusals. | Partly. The stand-in is term overlap and the queries use catalogue vocabulary. The "-78%" token figure is against the whole catalogue, not the ADS-007 baseline. |
| `m7/isolation-thresholds.proposed.json` | **Approve** | As written (all zero or 1.0). Add as a pilot precondition, not a gate value: F-02, F-03, and F-05 resolved or formally accepted, plus an independent security review. | A single leak ends the pilot and probably the product. Zero is the only acceptable number. | Mechanism (real REST and tool surfaces, local IdP). |
| `m7/reliability-thresholds.proposed.json` | **Amend** | Keep all values. **Add** a declared pilot availability target: >= 99.0% of business-hours requests end in a non-`internal_error` outcome, measured on staging. Add `wrong_answers_after_rebuild` = 0 (already implied; make it explicit for the at-least-once rebuild path). | The plan's ADS-075 acceptance says "declared availability", and none is declared. Users experience availability, not crash points. | Mechanism (simulated crashes and exceptions). |
| `m7/performance-thresholds.proposed.json` | **Amend** | Keep `p95_compile_policy_overhead_ms` <= 250 and the zero-error, fairness, and quota gates. Mark all latency gates "local smoke" and add the staging gates from the e2e row. Replace `assumed_prices` with real quotes before any cost gate counts. Change `answers_per_tenant_day` >= 100 to **>= 3 x expected pilot daily volume**, measured after an approved cost-unit calibration. For example, 20 users x 10 questions = 200, which gives a gate of 600. Keep `cost_per_answer_usd` <= 0.25 as a ceiling for the pilot business case, with a real-price re-measurement. | Users hitting a daily budget mid-afternoon is a very visible failure. The current unmet 92 < 100 is an uncalibrated artefact (a 200-unit query is among the cheapest), and 100 a day is too low for a meaningful pilot anyway. | **Yes**: an instant scripted model, a 100-row table, and placeholder prices. |
| `m7/provider-thresholds.proposed.json` | **Amend** | Change `model_calls_per_failing_run_max` from 1 to **2**, allowing exactly one automatic retry on transient provider errors (timeout, 429, 5xx), never on malformed output. Add `transient_provider_error_user_visible_rate` <= 0.01 on staging. Keep the other values. | Today a single flaky provider call (`flaky_first_call`) becomes a user-visible failure. Users should not have to press "Try again" for a provider blip. One bounded retry is not a retry storm. | **Yes**: the "providers" are distortions of the scripted model. `provider_wrong_answers` = 0 says nothing about a real model. |
| `m7/onboarding-thresholds.proposed.json` | **Approve** | As written. | Proves the product is not hard-coded to one tenant. Natural-language support for tenant B is not shown and should not be claimed in pilot materials. | Mechanism (intent is compiled directly; no natural language). |
| `m7/corpus-approval.proposed.json` | **Reject as pilot corpus; keep as regression corpus** | Require 25-50 real P0 questions from the data owner, a held-out set of >= 100 real pilot-style questions that is never used for tuning, and separate definition and results owner approvals. | The 30 "customer-style" cases are rephrasings that the scripted model was built to recognise. They cannot tell us whether pilot users get answers. | n/a |
| `prompt_registry/prompt-thresholds.proposed.json` | **Approve (mechanism)** | As written. | Invisible to users. It guarantees that released prompts cannot silently change. | Mechanism. |
| `review/review-thresholds.proposed.json` | **Approve (mechanism)** | As written. | Separation of duties protects users from self-approved corrections. | Mechanism (token reviewers, no real IdP). |
| `evaluation/evaluation-thresholds.proposed.json` | **Approve as a gate on the gate only** | As written. It must not be cited as evidence that any prompt change is safe for users. | `harmful_candidate_detection` = 1.0 only shows that the gate catches regressions *the keyword model exhibits*. | **Yes**: "the scripted model ignores instruction text". |
| `rollout/rollout-thresholds.proposed.json` | **Approve (mechanism)** | As written. | Rollback works on the controller. The runtime is not wired to it, so the pilot ships with pinned prompts. | Mechanism; observers are simulated. |
| `rollout/rollout-policy.proposed.json` | **Amend** | Keep `shadow_min_agreement` 1.0 for result fingerprints *on deterministic-model replays*. Add `min_requests_per_stage` >= 50. Keep `canary_fractions` [0.1, 0.5]. Keep `canary_max_error_rate` 0.0 for wrong answers, but add a separate `canary_max_false_refusal_increase` <= 0.05 absolute. Keep `approval_max_age_hours` 168. | At pilot volume, a 10% canary sees a handful of requests a day, so a stage needs a minimum sample size to mean anything. A real model will not reach 1.0 agreement on refusal choices; a prompt change that doubles refusals is a user regression, not an error. | Simulated. Not usable in the pilot because the runtime is unwired; recommend no prompt rollouts during the pilot. |
| `drift/drift-policy.proposed.json` | **Amend** | O-02 `success_rate` abs decrease: 0.10 -> **0.05** (critical). I-02 `clarification_rate`: keep 0.15 (warning). **Add** a `refusal_rate` abs increase of 0.10 (warning) and a `negative_feedback_rate` abs increase of 0.05 (critical). `min_samples` 30 is acceptable for pilot volume. | During a pilot, a 10-point drop in answers is a very bad week for users; I want to hear about 5. Refusal surges and thumbs-down are the signals closest to user pain. | Synthetic windows. |
| `drift/drift-thresholds.proposed.json` | **Approve (mechanism)**, plus a must-have | As written. Must-have for pilot: alert delivery to a real channel (today alerts go to an in-memory sink). | A monitor nobody sees protects no one. | Synthetic. |
| `poisoning/poisoning-thresholds.proposed.json` | **Approve (mechanism)** | As written. | Feedback from pilot users must never silently change answers. These gates protect that. | Mechanism (author-written attacks). |
| `security/security-thresholds.proposed.json` (context) | **Approve** | As written. `unresolved_critical_high_findings` must be rated by the independent reviewer, not by the implementing agent. | | Mechanism. |
| `quotas/quota-policy.proposed.json` (context) | **Amend** | Size `daily_cost_units` from calibrated units to >= 3 x expected volume. Define SLO "success" as *answer, clarify, review, or justified refuse*, not answer only. Keep 60 rpm and 4 concurrent runs per tenant for the pilot. | `success_target` 0.99 is ambiguous: correct refusals must not burn the error budget. | Placeholder. |
| `resilience/objectives.proposed.json` (context) | **Approve for pilot** | RPO and RTO of 900 s are fine for a limited pilot. Re-baseline on the staging database. | A 15-minute loss of in-flight runs is tolerable for analysts. | Simulated. |

## Outcome UX review

These findings come from `apps/analytics-web/src/governed/{views.tsx,workflow.ts,GovernedWorkspace.tsx}` and the outcome mapping in `services/analytics-api/app/runtime/analyze_service.py`, `ontology_node.py`, and `intent_echo.py`. Wording below is a suggestion only.

### Refuse

| Situation | What the user sees today | Problem | Suggested copy (suggestion only) |
|---|---|---|---|
| Intent-echo mismatch | "The question and the interpreted request do not match: metric not in question:revenue; grouping not in question:orders.status." plus `Reason: unsupported_request` | Raw codes with colons and internal IDs. The user cannot tell *what* was misread. | "I understood this as **total revenue by order status**, but your question doesn't mention revenue or status, so I didn't answer. Try naming the metric, for example 'revenue by status last month'." Use certified *labels*, not IDs, and echo the interpreted intent back. |
| Echo `unrecognized_grouping:region` | "...unrecognized grouping:region." | It is the most useful refusal in the product, but it reads like a stack trace. | "I can't break results down by **region** yet; it isn't a certified dimension. Available: status, month. [Ask the data owner to add it]" |
| Model said "unsupported" | "This question is not one the certified analytics can answer." + "Ask about a certified metric or dimension, or contact the data owner." | Acceptable, but there is no list of what *is* answerable and no contact. | Add "You can ask about: Revenue (by status, by month)." Link the catalogue and name the data owner. |
| Policy denial | "The request was refused by policy or review." with no remediation | Conflates policy denial and reviewer rejection. There is no next step. | Policy: "Your access for purpose **finance-reporting** doesn't include this data. Request access from <owner>." |
| Reviewer **rejected** the plan | Same "refused by policy or review", `policy_restricted` | The requester can't tell that a person rejected it, or why; the reviewer's note is not shown. | New code `review_rejected`: "A reviewer declined to run this query." Add the reviewer's note if present. |
| Review **expired** | `stale_metadata`: "The request could not proceed against current certified context or review." + "Resubmit the request." | Wrong reason code. Users will think the data is stale. | New code `review_expired`: "No reviewer approved this in time (expired <time>). Ask again, or ping a reviewer." |
| Context search down (ADS-075) | Refusal `stale_metadata` with "Resubmit" | An outage shown as a refusal. It is not retryable in the UI because refusals have no Try again button. | Map to a `failed` outcome with retryable true: "Search for definitions is temporarily unavailable. Try again in a minute." |
| Reason code line | `Reason: unsupported_request` shown to every user | Fine for support, noisy for analysts. | Move it into a collapsible "Details for support" section together with the run ID. |

### Clarify

- **Prompt and choices are machine text.** The prompt is "Select the intended certified metric." The buttons are labelled with raw candidate IDs (`label=c`). Suggestion: "Which **revenue** did you mean?" with buttons "Gross revenue (orders.gross_revenue): all paid orders, before refunds" showing label, one-line definition, and owner.
- **The question the user asked is not shown back.** Show "You asked: '...'" above the choices.
- **Free text is disallowed and the fallback is a dead end.** "Confirm the selection." appears with no choices, and the UI then says "No options are available; rephrase your question." Suggestion: provide a "None of these: rephrase" button that pre-fills the question box.
- **The clarification limit (2) is invisible.** A third ambiguity ends the run as an error. Say "I still couldn't pin this down after two clarifications. Try a more specific question."
- **Only the requester can answer.** That is correct, but the error ("Only the person who asked can answer a clarification") should appear before the click, not after.

### Review

- **The requester sees enabled Approve and Reject buttons** (`allowed_actions` is always `["approve","reject"]`). Clicking returns `review_not_permitted`. Suggestion: hide or disable them for the requester and show "Waiting for a reviewer. Share this link: <link>". Have the API return `allowed_actions: []` for the requester.
- **No routing.** A reviewer must paste a run ID into "Open a run (reviewers)", and nobody is notified. In a pilot, a review outcome is effectively a dead end unless reviewers are told. A **must-have** is at least a shareable link and a reviewer notification (email or chat), or a review queue.
- **The reason is a raw code** (`cost_threshold`, `policy_review`, `uncertified_intent`, `uncertified_exploration`, `human_approval`). Suggestion: "This query is estimated to scan more data than your team's auto-approve limit (est. 263 units, limit 200)." and "This uses a metric that is not yet certified, so a reviewer must confirm it."
- **The plan is not shown to the reviewer.** They see only a fingerprint and are asked to approve blind. Show the interpreted intent (metric, dimensions, filters, time range), the estimated cost, and the policy filters that will be applied.
- **The expiry has no context.** Show "Expires in 23 h (Thu 14:00)" and what happens after it expires.

### Failed

- **Title and message duplicate each other** ("The request could not be planned." twice for `planner_unavailable`).
- **`planner_unavailable` covers malformed model output**, which is not an outage. Suggestion: "I couldn't turn this question into a query. Try rephrasing it, or try again." Keep it retryable, but it should not count as availability loss in the SLO.
- **`internal_error` "The answer is unavailable."** (rows lost after a restart): say "This answer needs to be recomputed. Try again." because it is retryable.
- **The retry semantics are now right.** "Try again" uses a new idempotency key and `retry_guidance` exists. The web tests for this were not run (`node_modules` absent), so this must be run before the pilot.
- **Polling gives up silently.** After 30 one-second polls, `pollUntilSettled` returns "running" and the card still says "This page checks for the result automatically", but polling has stopped. With a real model and warehouse, P99 may exceed 30 s. Suggestion: back off up to 2-3 minutes, then show "Still running. [Check again]".

### Answer (where it affects trust)

- **`assumptions` are never rendered.** If the system assumed a time range, timezone, or default filter, users must see it. This is a must-have; it is the main defence against "right number, wrong question".
- **The interpreted question is not echoed.** Show "Showing: total revenue by order status, all time" above the number. This also makes intent-echo refusals understandable.
- **"Replay and verify" re-reads the stored run.** It does not re-execute anything, so "verify" overclaims. Suggested label: "Re-check stored evidence".
- **"Verified in browser"** is a good trust signal, but it should explain that it means "every number in this sentence appears in the cited cells".
- **Result tables are silently truncated at 50 rows.** Say "Showing 50 of N rows".
- **Column headers are raw.** Use certified labels.
- **Connection UX.** Users paste an access token and type a purpose free-hand. For a pilot this must be SSO with a purpose picker (only authorised purposes), or every first session will start with `purpose_not_authorized`.

## Pilot success criteria and go/no-go bar

### Preconditions (all must be true before I would sign "go")

1. **Real model selected and pinned** (model, version, prompt version in the ADS-079 manifest). It has been evaluated on the owner-approved real-question set described below, *not* on the reference phrasings.
2. **Real warehouse.** A staging PostgreSQL (or the customer's target) has seeded or replicated pilot data, and live OpenSearch has the pilot catalogue. Both were run under an explicit, separately authorised validation task.
3. **Owner-approved corpus.**
   - 25-50 real P0 questions from the pilot data owner.
   - A >= 100-question held-out pilot set that has never been used for tuning, including >= 25 near-miss and >= 15 ambiguous questions.
   - Definitions and expected results approved by two different named people.
4. **All gates below met on that set, on staging, on one pinned release candidate.**
5. **Thresholds and policies approved** (as amended) by named people with dates, in the manifest.
6. **Security.** An independent security review has been completed with no open critical or high findings. F-02 (`run_id_key` mandatory) is fixed. F-03 (`min_cohort` set) is fixed before any personal-data dataset. F-05 visibility is decided.
7. **Outcome UX fixes shipped** (must-have list below) and web tests run green.
8. **Operations.** An operations game day has walked the `ops-*` runbooks with someone who did not write them, and drift alerts reach a real channel.
9. **Sign-offs.** All five ADS-079 sign-offs (product, engineering, data owner, security, operations) are signed against one manifest digest.

### Gates with a real model and real warehouse (staging, pinned RC)

| Dimension | Go bar |
|---|---|
| P0 questions answered with correct rows | **100%**. Any wrong P0 is an automatic no-go. |
| Wrong answers among all answered questions | **<= 1%**, and 0 on P0 |
| Answer coverage on in-scope held-out questions | **>= 85%** answered correctly (the rest clarify or refuse) |
| False refusal of valid questions | **<= 15%** |
| Clarification rate on unambiguous questions | <= 10% |
| Clarification resolution | >= 80% of clarifications end in a correct answer after one choice |
| Refusal recall on unsupported or unsafe questions | 100% |
| Near-miss questions answered with the wrong metric | 0 |
| Policy and tenant violations, raw-model SQL executed | 0 |
| Evidence completeness, replay fingerprint equivalence | 100% |
| End-to-end latency, staging at pilot concurrency (>= 10 concurrent) | P50 <= 6 s, P95 <= 15 s, P99 <= 45 s |
| Transient provider errors reaching the user | <= 1% |
| Cost per answered question (real prices) | <= agreed ceiling (proposed $0.25) |
| Daily budget | >= 3 x expected pilot volume (calibrated units) |
| Availability (business hours, staging soak >= 5 days) | >= 99.0% of requests end in a non-`internal_error` outcome |

### Pilot-period success criteria (to judge the pilot itself, after go)

- Cohort: 10-25 named analysts at one tenant, one domain, 4-6 weeks, with a weekly review of *every* refusal and *every* thumbs-down.
- >= 90% of answered questions rated correct by users, with feedback-based spot checks by the data owner.
- >= 70% of pilot users ask >= 5 questions a week by week 3 (adoption).
- Median time from question to trusted number is below the current baseline (ticket to analyst), measured by survey.
- Reviews are decided within the expiry window >= 90% of the time.
- 0 Sev-1 incidents.

### Kill criteria (stop the pilot immediately)

- Any confirmed wrong answer on a certified P0 metric that a user acted on.
- Any cross-tenant or policy leak.
- Any executed SQL not produced by the deterministic compiler.
- A wrong-answer rate above 2% over any rolling 100 answered questions.

### Today

**No-go.** Preconditions 1-9 are all open. Every correctness gate that matters to users has only been measured on a scripted model.

## Prioritised open items

### Must-have before pilot

1. **Real-model evaluation.** Select and pin the model, then run the e2e, abstention, and provider suites with it on the real-question set. This is the single largest unknown, and I cannot sign anything until it exists.
2. **Owner-approved real corpus** (P0 plus held-out plus near-miss), with independent definition and results approvals.
3. **Staging with a real warehouse and live OpenSearch.** Re-baseline latency and cost, approve a cost-unit calibration (M7-H4 mechanism), and resize quota and `answers_per_tenant_day`. This resolves the only unmet gate.
4. **Approve the threshold files** with the amendments above, especially *wrong-answer rate* as its own gate.
5. **Outcome UX fixes:**
   - human-readable refusal and clarify copy using certified labels;
   - echo the interpreted intent and render `assumptions`;
   - separate `review_rejected` and `review_expired` codes;
   - show the context-search outage as a retryable failure;
   - no Approve or Reject buttons for the requester;
   - show the plan to the reviewer;
   - polling timeout messaging;
   - "Showing 50 of N".
6. **Review routing.** A shareable run link plus a reviewer notification or queue. Without it, review outcomes stall.
7. **One bounded automatic retry** for transient provider errors.
8. **SSO login and a purpose picker** instead of a pasted token and free-text purpose (real IdP; enforce the `agent:`/`service:` prefix convention).
9. **Security.** F-02 fixed, F-03 `min_cohort` set, F-05 decided, and the independent security review done.
10. **Independent code review** of the user-facing path (ADS-040..049, the web workspace, M7-H1..H4). Run the web test suite.
11. **Drift alerts delivered** to a real channel. Add refusal-rate and negative-feedback monitors.
12. **Retention rule** for the durable plan and policy-value tables (M7-H1). They store filter literals and identity claims, so the data owner must decide retention before real data.
13. **Regenerate stale reports.** ADS-077 still says "no intent-echo check exists", and ADS-075 says "no retry guidance". The ADS-073 report says 4 near-miss questions while the packet says 8. The evidence a signer reads must be current.

### Can follow (after pilot start or after pilot)

- Wiring the runtime to the prompt registry and rollout pointer. The pilot runs on pinned prompts with no prompt rollouts.
- Production drift threshold tuning (needs pilot traffic).
- Second-tenant natural-language onboarding and broader Ossie coverage.
- Exactly-once execution across processes (stored result rows).
- Model confidence calibration (none is claimed; keep claiming none).
- Free-text clarification answers.
- Per-person differencing audit (beyond `min_cohort`), unless personal data is in pilot scope.
- A capacity test beyond pilot load.

## Questions for the human owner

1. **What does the recorded `M7: final_go_no_go = approved` mean to you?** It conflicts with ADS-079 (`pending_human_review`, six blockers, no signatures). Should it be re-scoped in the manifest (in your words) as "M7 evaluation milestone accepted, pilot go/no-go still pending"?
2. **Wrong answers versus refusals:** do you accept the principle that the 5% slack in `answer_result_equivalence` may only be spent on refusals and clarifications, with a separate wrong-answer gate of <= 1% (0 on P0)?
3. **What false-refusal rate will you tolerate in the pilot?** I propose <= 15%. A stricter number may force loosening the lexical intent-echo check, which raises wrong-answer risk.
4. **Pilot cohort and volume:** how many users, how many questions a day, and for how long? This sets the daily budget (>= 3 x volume), the canary minimum sample sizes, and drift `min_samples`.
5. **Latency:** is P95 <= 15 s end-to-end acceptable to your pilot users, with visible progress? Or do they expect BI-dashboard speed?
6. **Who is the pilot data owner?** Who will be the definition owner and the results owner for the real-question corpus, and are they different people?
7. **Who reviews?** Which people or groups are reviewers for `cost_threshold` and `uncertified_intent` reviews, what is the expected turnaround, and is 168 h expiry right or should it be 24 h for a pilot?
8. **Is any personal data in pilot scope?** If yes, F-03 `min_cohort` (suggested starting value 10) must be set and owner-approved before onboarding.
9. **Uncertified exploration:** should the pilot allow `uncertified_exploration` via review at all, or should only certified metrics be answerable during the pilot (simpler, and safer for trust)?
10. **Real model and warehouse validation:** will you authorise, as a separate explicit task, staging validation against a real PostgreSQL, OpenSearch, and model provider? None of the go criteria above can be measured without it.
