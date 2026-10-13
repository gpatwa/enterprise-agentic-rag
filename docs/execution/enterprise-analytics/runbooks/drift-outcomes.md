# Drift runbook: outcome mix

Alerts `drift-outcomes` (ADS-058). Advisory only: an alert starts nothing automatically and no monitor changes a run,
a release, a pointer, or a threshold. A person decides what to do.

## Symptom

The share of succeeded runs falls, or the mix of terminal outcomes shifts.

## Likely causes

- A new class of questions is being refused, over budget, or failing validation.
- A policy or contract change altered what is allowed.
- An upstream gateway or warehouse problem is failing executions.

## Read-only checks

- Group recent terminal runs by kind and by error code (counts only).
- Check evidence envelopes for the dominant error codes and policy reasons.
- Compare against the golden suite's last report.

## Mitigation

- Fix the upstream cause (gateway, policy, context) through the normal reviewed path.
- Re-run the golden suite and the targeted corpora before and after a fix.

## Do not

- Do not edit goldens, thresholds, the case index, the semantic registry, or the runtime prompt to make the alert stop.
- Do not delete or rewrite runs, evidence envelopes, or feedback; they are append-only for a reason.
- Do not mark any packet complete or any gate approved because an alert cleared. Approvals are the user's.
