# Operations runbook: rolling upgrade

A release changes persisted state or the graph, ADS-068. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

Mixed-version workers will read each other's checkpoints during a rolling upgrade.

## Likely causes

- A new required field on persisted state (old readers reject unknown fields by design).
- A changed node or edge allowlist for a graph version.

## Read-only checks

- Run the checkpoint-fixture tests: pinned fixtures from each release must still load.
- Check any new field is optional with a default and is not written until every worker can read it.

## Mitigation

- Use expand-then-contract: ship the reader first, then the writer.
- Regenerating the fixtures is a compatibility decision, never a way to make a test pass.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
