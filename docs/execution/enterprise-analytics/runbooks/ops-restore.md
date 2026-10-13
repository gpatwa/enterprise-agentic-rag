# Operations runbook: restore

A restore is needed, or the restore drill fails, ADS-068. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

The control store is lost or corrupt, or `make analytics-resilience-drill` reports `restore` failed.

## Likely causes

- Database loss or corruption.
- A backup that is corrupt, incomplete, or from another schema revision (refused with a stable code).
- Recovery time or data-loss window over the proposed objectives.

## Read-only checks

- Verify the backup files first: the verifier reports `backup_corrupt`, `backup_table_missing`, `backup_manifest_tampered`, or `backup_manifest_unreadable`.
- Restore only into a fresh, migrated, empty database; `target_not_empty` and `schema_revision_mismatch` are refusals, not bugs.
- After restore, the evidence chain of every tenant is re-verified; `restored_evidence_chain_broken` is an integrity incident.

## Mitigation

- Restore the newest backup that verifies; runs written after it are lost (the data-loss window).
- Answer rows and explanations are held in process memory and do not survive restart, so reviews paused across the outage fail closed and must be re-asked.
- Native database backup and point-in-time recovery are the production tools.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
