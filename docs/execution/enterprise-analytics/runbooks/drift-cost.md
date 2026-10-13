# Drift runbook: cost

Alerts `drift-cost` (ADS-058). Advisory only: an alert starts nothing automatically and no monitor changes a run,
a release, a pointer, or a threshold. A person decides what to do.

## Symptom

The mean observed cost per run is well above the baseline.

## Likely causes

- Queries scan more data (new datasets, wider time ranges).
- Estimator cost units drifted from the warehouse's real behaviour (units are per dialect and uncalibrated).
- A candidate prompt or intent change selects heavier queries.

## Read-only checks

- Compare estimated and observed cost units for recent runs.
- Look at which semantic ids the costly runs used.
- Check recent promotions in the rollout pointer history.

## Mitigation

- Tighten budgets or review approval thresholds through the reviewed path, with the user's approval.
- Investigate a promoted prompt; a manual rollback is a human decision.

## Do not

- Do not edit goldens, thresholds, the case index, the semantic registry, or the runtime prompt to make the alert stop.
- Do not delete or rewrite runs, evidence envelopes, or feedback; they are append-only for a reason.
- Do not mark any packet complete or any gate approved because an alert cleared. Approvals are the user's.
