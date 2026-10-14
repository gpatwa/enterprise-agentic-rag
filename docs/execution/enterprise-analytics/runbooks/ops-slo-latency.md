# Operations runbook: slo latency

Alert `slo_latency` (warning), ADS-066. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

The tenant's p95 latency over the slow window is above the objective while errors are within budget.

## Likely causes

- A slow warehouse or an expensive query shape.
- Context retrieval slow or degraded.
- Queueing behind the concurrency cap.

## Read-only checks

- Compare per-layer span durations for slow runs by `run_ref`.
- Check `cost_by_purpose` for a heavier mix.
- Check drift `drift-latency` for the same window.

## Mitigation

- Reduce load or raise capacity through the user's change process.
- Review the latency objective only with the user's approval.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
