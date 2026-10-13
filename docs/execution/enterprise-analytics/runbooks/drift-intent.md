# Drift runbook: intent extraction

Alerts `drift-intent` (ADS-058). Advisory only: an alert starts nothing automatically and no monitor changes a run,
a release, a pointer, or a threshold. A person decides what to do.

## Symptom

More runs fail with `malformed_model_output`, or more runs end asking for clarification.

## Likely causes

- The model or prompt changed and no longer follows the AnalyticalIntent schema.
- New vocabulary produces ambiguous labels in the ontology.
- A prompt candidate was promoted or the model provider changed behaviour.

## Read-only checks

- List the error codes of recent failed runs (counts only).
- Check the rollout pointer history and which model/prompt version the deployment uses.
- Look at ADS-051 triage categories for `intent` and `ontology`.

## Mitigation

- If a promoted prompt is suspected, a person can request a manual rollback (ADS-057); the monitor will not.
- Review ambiguous labels with the semantic owners.

## Do not

- Do not edit goldens, thresholds, the case index, the semantic registry, or the runtime prompt to make the alert stop.
- Do not delete or rewrite runs, evidence envelopes, or feedback; they are append-only for a reason.
- Do not mark any packet complete or any gate approved because an alert cleared. Approvals are the user's.
