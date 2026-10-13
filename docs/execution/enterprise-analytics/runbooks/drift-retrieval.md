# Drift runbook: retrieval quality

Alerts `drift-retrieval` (ADS-058). Advisory only: an alert starts nothing automatically and no monitor changes a run,
a release, a pointer, or a threshold. A person decides what to do.

## Symptom

More runs retrieve no context items, or the mean number of retrieved items drops.

## Likely causes

- The OpenSearch context index lost documents, or the index mapping changed.
- A snapshot was published without the expected certified assets.
- Query volume shifted to topics the context does not cover.

## Read-only checks

- Count documents for the tenant and snapshot in the context index (read-only search).
- Compare `context_pack` item counts in recent runs with the baseline window.
- Check the ADS-051 triage records for a rise in `retrieval` categories.

## Mitigation

- Re-index the published snapshot (the publish hook is idempotent) after confirming the cause.
- Raise a change proposal (ADS-052) for a missing context edge; it needs independent review.

## Do not

- Do not edit goldens, thresholds, the case index, the semantic registry, or the runtime prompt to make the alert stop.
- Do not delete or rewrite runs, evidence envelopes, or feedback; they are append-only for a reason.
- Do not mark any packet complete or any gate approved because an alert cleared. Approvals are the user's.
