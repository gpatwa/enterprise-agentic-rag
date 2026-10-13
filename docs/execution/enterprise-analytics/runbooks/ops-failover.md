# Operations runbook: failover

A worker died mid-run, runs stay `running`, or the failover drill fails, ADS-068. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

Runs have stopped progressing, or concurrency slots stay held after a worker crash.

## Likely causes

- A worker crash or restart.
- A paused worker waking up and trying to continue (it is fenced off by a stale fencing number).
- A lease duration longer than expected.

## Read-only checks

- Diagnose the run (`ops-run-diagnosis`): a run in `running` with an expired lease is a crashed worker.
- Another worker takes over only after the lease expires; a live lease is refused with `LeaseUnavailable`.
- A stale worker's write is rejected with `StaleWorkerError`; that is the safe outcome.

## Mitigation

- Wait for the lease to expire, then resume the run from its last checkpoint; no manual edit of run rows is needed.
- If takeover does not finish the run, treat it as a defect and capture the run reference.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
