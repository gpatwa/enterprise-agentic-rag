# ADS-019: Context Quality Evaluation

Status: **Complete**
Milestone: M1
Depends on: ADS-011, ADS-012, ADS-013, ADS-014, ADS-015, ADS-016, ADS-017, ADS-018

## Deliverable

`services/analytics-api/app/context/quality.py` provides a deterministic
`ContextQualityReport` and `evaluate_context_quality` gate. The report covers
asset and certification counts, provenance coverage, stale metadata,
unresolved merge conflicts, and context-pack token utilization. Incomplete
provenance, stale metadata, or unresolved conflicts produce explicit blocking
reasons and make the context non-actionable.

## Evidence

- `services/analytics-api/app/context/quality.py`
- `services/analytics-api/tests/test_context_m1.py`
- `scripts/verify_context_local.py` via `make verify-context-local`
- Stale and incomplete-provenance cases produce actionable=false with specific
  blocking reasons.
- Live local verification passed for healthy and stale context snapshots.

## Boundary

This is a deterministic pre-action quality gate, not a model judge or a full
semantic-certification decision. Threshold approval and broader end-to-end
evaluation remain human-reviewed M1/M7 work.
