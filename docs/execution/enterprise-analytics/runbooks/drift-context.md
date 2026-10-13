# Drift runbook: context freshness

Alerts `drift-context` (ADS-058). Advisory only: an alert starts nothing automatically and no monitor changes a run,
a release, a pointer, or a threshold. A person decides what to do.

## Symptom

More runs end `review_required` with a `stale_context` error, or the snapshot a run used is older than the limit.

## Likely causes

- The refresh worker (ADS-044) stopped or its sources failed, so the published snapshot is not being re-verified.
- A tenant's context snapshot was never published or points at a missing registry entry.
- The ontology or catalog source is returning empty or partial reads (the worker reports these as failed fetches).

## Read-only checks

- Read the latest refresh report: which sources are `failed` or `reused_stale`.
- `current_snapshot()` for the tenant: does it raise `StaleSnapshotError` or `NoSnapshotError`?
- Compare snapshot ids in recent runs' evidence envelopes against the published pointer.

## Mitigation

- Restore the failing source or re-run the refresh worker; new runs pick up the new snapshot, existing runs stay pinned.
- If a source is intentionally retired, record that decision with the user before changing the worker policy.

## Do not

- Do not edit goldens, thresholds, the case index, the semantic registry, or the runtime prompt to make the alert stop.
- Do not delete or rewrite runs, evidence envelopes, or feedback; they are append-only for a reason.
- Do not mark any packet complete or any gate approved because an alert cleared. Approvals are the user's.
