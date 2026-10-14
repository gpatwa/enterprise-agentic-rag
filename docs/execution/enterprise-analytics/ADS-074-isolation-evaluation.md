# ADS-074: Security, Tenant-Isolation, and Policy Adversarial Evaluation

Status: **Review** (a local test matrix; thresholds **proposed, not approved**; **not an independent security review**)
Milestone: M7 (wave 7B)
Depends on: ADS-067, ADS-070

## Decisions made under the user's delegation ("make the decision")

1. **A probe matrix across surfaces, with real runs.** 24 hostile probes against a run that answered and a run paused for review, over REST and the agent-tool surface: another tenant
   (read, feedback, clarify, review, idempotency-key reuse, tool status and evidence), purposes the caller lacks or that differ from the run's, the requester approving their own review,
   an automated caller and a delegated agent deciding a review, a stale plan fingerprint, and forged/expired/wrong-audience/wrong-issuer/missing/malformed tokens.
2. **A probe passes only if it is refused AND nothing of the victim's run (ID, rows, plan fingerprint) is in the response.**
3. **Fold in the earlier evidence.** The ADS-067 security corpus (28 cases) and the ADS-070 policy-denied, tenant-isolation, and refusal cases (both dialects) are re-run; their results are gates here.
4. **Each defence is shown able to fail.** Tests remove one defence at a time (tenant scoping, purpose check, token verification, the automated-caller rule) and show the matching gate fails.
5. **Findings are carried, not hidden.** F-02, F-03, and F-05 are still not resolved in the findings register and are listed in the report.

## Deliverable

- `reference_stack/isolation_eval.py`, `m7/isolation-thresholds.proposed.json`, `make analytics-m7-isolation`, report `reports/ADS-074-isolation-report.{md,json}`, `tests/test_ads074_isolation.py`

## Boundary

- Zero violations here is not a statement that none exist. A caller is treated as automated only by an id prefix (`system:`, `model:`, `agent:`, `service:`) or a delegation claim; an automated actor with an
  ordinary-looking id would pass as a human reviewer, so identity-provider configuration must enforce the convention (recorded as a limitation).
- Local issuer only; no real IdP, no network or storage isolation. The independent security review the plan requires, and approval of the thresholds, are the user's.
