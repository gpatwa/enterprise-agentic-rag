# ADS-067: Threat Model, Prompt-Injection, Exfiltration, and Inference Suite

Status: **Review** (implemented and locally verified; **not** an independent security review)
Milestone: M6 (wave 6C)
Depends on: ADS-061 to ADS-066

## Decisions made under the user's delegation ("make the decision")

1. **Adversarial evaluation first, then fix what it finds.** The corpus was run against the real pipeline before any hardening; the
   findings below are what it surfaced, not what was assumed.
2. **A hijacked model is simulated by replacing its output.** The pipeline's controls (strict intent schema, certified IDs, deterministic
   compilation, bound parameters) are what is measured; a real model's resistance to injection is not.
3. **`known_gap` cases keep the register honest.** A behaviour that is *not* prevented is asserted as such in the corpus, so the findings
   register cannot drift from reality.
4. **Severity is mine; acceptance is not.** F-03 is rated *high* in general and *medium at pilot scope* (internal business data, authorized
   analysts); what to do about it is the data and security owners' decision. The gate counts critical or high findings at pilot scope.
5. **Inference controls default off.** A minimum cohort changes what users can ask, and the right k depends on the data, so it ships as an
   explicit deployment option.

## Deliverable

- `docs/execution/enterprise-analytics/security/threat-model.md`: assets, actors, trust boundaries, and 22 threats (prompt injection, hijacked
  model and explainer, identity, delegation, tenancy, run IDs, SQL, runaway queries, wrong results, time, inference, data plane, evidence, telemetry,
  audit, the learning loop, availability, tool surface, prompt registry), each with its controls, **its verification (test file::name pairs)**,
  and its residual risk. A test checks that every referenced test exists, so the table cannot silently go stale.
- A 28-case pinned corpus (`reference_stack/security/security-corpus-v1.json`) and `make analytics-security-eval` (report in `reports/`).
- **Hardening that came out of it** (each tied to a finding and a test):
  - *F-01* the compiler refuses grouping by an unbucketed temporal dimension and grouping by a metric's grain key;
  - *F-02* optional `GovernedAnalyzeService(run_id_key=...)` makes run IDs an HMAC (`run_id_for`; wrappers use it);
  - *F-03* optional `min_cohort` (compiler `HAVING COUNT(*) >= k`; validation treats a suppression shortfall as a warning and a surplus still as a
    fanout; an all-below-k population is a **policy refusal**, not an outage; filters on the entity key are refused when it is on);
  - *F-04* an empty result with an empty control total is a valid "no data" answer (it used to fail as an internal error);
  - *F-06* both gateways pin the session time zone to UTC.

## Findings register (also rendered in the report)

| ID | Severity | Status | Finding |
|---|---|---|---|
| F-01 | high | resolved | Grouping by an unbucketed timestamp returned one row per order |
| F-02 | high | mitigated | Run IDs derivable by a colleague from the user ID and a guessable key; HMAC key is a **deployment requirement** (the default stays derivable) |
| F-03 | high (pilot scope: medium) | **open, decision needed** | Small cohorts and exact differencing: `min_cohort` is available but off, and differencing across two large cohorts is still possible |
| F-04 | low | resolved | No matching rows failed as an internal error |
| F-05 | medium | accepted by design | Same-tenant callers holding a run ID can read its status and evidence |
| F-06 | medium | resolved | A time range depended on the server's time zone (found because the differencing probe summed 4950 where a range covering every order should give 5050; the host was on UTC-7) |

## Evidence

- `tests/test_ads067_security.py` (17 tests): the corpus meets its proposed thresholds and stays unapproved; hostile-model, injection, tenant,
  token, and error-body controls hold; hostile explainers degrade to evidence only; every finding cites evidence and none is critical or high and
  unresolved at pilot scope; the documented gaps stay true; **the evaluation fails when a control is weakened** (ignoring `min_cohort` fails the
  inference cases); a wrong expectation or a changed corpus is detected; **every verification reference in the threat model exists**; the compiler
  refuses row-level groupings; the minimum cohort is validated, bounds the SQL, and suppression is a warning while a fanout still blocks; an empty
  result is valid; keyed run IDs cannot be derived; the session time zone is UTC; and nothing mounts the evaluation.
- `make analytics-security-eval`: 28/28 cases and all seven proposed gates are met.

## Decisions that belong to people

- **F-03:** whether to enable `min_cohort` and its value per dataset, and whether personal or restricted data may be onboarded without per-person
  query auditing. Until then no such dataset should be onboarded.
- **F-02:** a deployment must set `run_id_key` (a checklist item for the ADS-069 runbooks).
- **F-05:** whether to tighten run reads to the requester and reviewers.
- **Accepting residual risks, the proposed corpus thresholds, and the M6 `security_and_operations_review`.**

## Boundary

- Not a penetration test, not an independent review, and no real model, identity provider, or warehouse. Side channels (timing, caches), supply chain,
  secrets management, and novel attacks are not covered.
- Differencing across a person's sequence of queries needs per-person query auditing, which is not built.
- The mitigations are available in code and tested, but none is *enabled* in a deployment (nothing is deployed): `min_cohort` and `run_id_key`
  are configuration a deployment must choose.
