# Drift runbook: latency

Alerts `drift-latency` (ADS-058). Advisory only: an alert starts nothing automatically and no monitor changes a run,
a release, a pointer, or a threshold. A person decides what to do.

## Symptom

The 95th percentile of run duration is well above the baseline.

## Likely causes

- Slower warehouse or gateway responses, larger scans, or queueing.
- More clarification or review rounds in the graph.
- Model provider slowness.

## Read-only checks

- Compare run durations per node from the transition history.
- Check gateway timeouts and estimated costs in recent runs.
- Check infrastructure dashboards for the warehouse and model provider.

## Mitigation

- Reduce load or fix the slow dependency; consider lowering budgets only through a reviewed change.
- Do not raise timeouts silently.

## Do not

- Do not edit goldens, thresholds, the case index, the semantic registry, or the runtime prompt to make the alert stop.
- Do not delete or rewrite runs, evidence envelopes, or feedback; they are append-only for a reason.
- Do not mark any packet complete or any gate approved because an alert cleared. Approvals are the user's.
