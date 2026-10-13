# Operations runbook: slo burn

Alerts `slo_fast_burn` (page) and `slo_slow_burn` (warning), ADS-066. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

A tenant is consuming its error budget faster than allowed: system failures, not refusals the caller caused, are above the target.

## Likely causes

- A dependency is failing (warehouse, context index, control store).
- A bad release (check the rollout pointer and the latest deploy).
- A worker crash storm leaving runs unfinished.

## Read-only checks

- Dashboard alerts for the tenant and any gate row that is failing.
- Pick a failed run from the audit trail and diagnose it with `ops-run-diagnosis`.
- Compare traces by `run_ref` to find the failing layer (api, graph, context, gateway, evidence).

## Mitigation

- Fast burn pages a person; stop any in-flight rollout through the reviewed path (a rollback is a human decision).
- Fix or fail over the dependency (`ops-failover`, `ops-restore`).

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
