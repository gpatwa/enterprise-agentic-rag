# Operations runbook: run diagnosis

Any run the operator needs to explain or replay, ADS-069. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

A request ended in a refusal, an error, or never finished, and someone needs to know where and why.

## Likely causes

- Policy refused it (`policy_restricted`), the question was ambiguous, or review was required.
- A node failed (`failed` terminal) or the worker died (run still `running` with an expired lease).
- The history has a gap, which means tampering or a restore problem.

## Read-only checks

- Diagnose by run reference: the diagnosis lists the status, terminal kind, the path of nodes, whether the transition history is contiguous, and evidence ids.
- A contiguous history that ends in a terminal node is a clean decision; read the terminal kind.
- A run still `running` after its lease expired: see `ops-failover`.
- Replay is deterministic: submitting the same request with the same idempotency key returns the same run and the same diagnosis digest.

## Mitigation

- Tell the caller the reason code; answer rows are never reconstructed from the diagnosis.
- If the history is not contiguous, treat it as an integrity incident and open `ops-restore`.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
