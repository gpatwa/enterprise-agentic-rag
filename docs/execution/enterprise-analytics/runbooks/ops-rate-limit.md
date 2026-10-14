# Operations runbook: rate limit

Alerts `rate_limited` and `concurrency_limited` (warning), ADS-066. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

Requests from one tenant are being refused with `rate_limited` or `concurrency_limited`, with a `Retry-After` hint.

## Likely causes

- A client without backoff, or a burst larger than the bucket.
- Runs that never finish and hold concurrency slots (a stuck worker; see `ops-failover`).
- A limit set below legitimate use (the shipped policy is proposed, not tuned).

## Read-only checks

- Dashboard tenant row: `in_flight` high with few `admitted` suggests held slots; `rate_limited` growing suggests a hot client.
- Diagnose a slow run with `ops-run-diagnosis` to see whether it is stuck or just slow.
- Confirm other tenants' rows are unaffected (limits are per tenant).

## Mitigation

- Ask the client to back off using the returned retry hint.
- If slots are held by dead workers, follow `ops-failover` (leases expire on their own).
- A policy change is the user's decision.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
