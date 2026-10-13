# Operations runbook: cost budget

Alerts `cost_budget_warning` (page-free) and `cost_budget_exhausted` (page), ADS-066. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

A tenant's attributed cost units today crossed the warning fraction, or reached the daily budget so new work is refused with `cost_budget_exhausted` until 00:00 UTC.

## Likely causes

- A genuine spike in demand, or a heavier query mix (wider time ranges, new datasets).
- A loop in a client or agent retrying cost-bearing calls.
- Estimator cost units that no longer match real warehouse cost (units are per dialect and uncalibrated).
- A denial-of-wallet attempt: many distinct questions from one tenant.

## Read-only checks

- Dashboard tenant row: `day_cost_units` and `cost_by_purpose` show which purpose is spending.
- Count recent runs per caller and per purpose from the audit trail (counts only).
- Check the rollout pointer history for a recent promotion that selects heavier queries (`drift-cost`).

## Mitigation

- The refusal is the mitigation: other tenants are unaffected and the budget resets at 00:00 UTC.
- If the budget is too small for legitimate use, ask the user to approve a per-tenant override in the quota policy.
- If a client is looping, contact the tenant owner and have that client back off.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
