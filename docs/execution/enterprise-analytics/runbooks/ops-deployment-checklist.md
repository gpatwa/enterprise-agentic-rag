# Operations runbook: deployment checklist

Before any deployment or environment change, ADS-066..068. Nothing here is automated. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

A deployment would run without a setting that the security or resilience findings depend on.

## Likely causes

- `run_id_key` unset, so run IDs are derivable by anyone who knows the idempotency key.
- `min_cohort` unset, leaving small-cohort aggregates unsuppressed (open finding F-03).
- Session timezone not UTC, a durable control store not configured, or process-local quota state across several replicas.

## Read-only checks

- Confirm `run_id_key` is a secret supplied by the platform.
- Confirm `min_cohort` is set to the value the security owner decided.
- Confirm quota state is shared if more than one replica runs (it is process-local today).
- Confirm a verified backup exists and the restore drill passed on the target database.

## Mitigation

- Do not deploy until the settings are configured by the owners of those decisions.
- Live validation against PostgreSQL, OpenSearch, or an identity provider is the user's explicit decision.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
