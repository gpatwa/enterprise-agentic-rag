# IMD-050: Consented Interaction Ingestion and Impression Validation

## Objective

Ingest typed interaction events with valid impression lineage and consent.
Duplicate/replayed/unknown actions are rejected or idempotent; direct organic
navigation remains a separate typed path.

## Dependencies and Reads

- IMD-005, IMD-013, and IMD-059 are merged.

## Owned Files

- Create `services/discovery-api/app/events/ingestion.py`.
- Create `services/discovery-api/tests/test_event_ingestion.py`.

## Requirements

- Validate tenant/user/request/impression lineage, event version, consent,
  timestamp skew, typed payload, and synthetic marker.
- Enforce bounded batch/idempotency semantics and explicit rejected reasons;
  never mutate an existing event on replay.
- Keep direct/organic navigation separate from recommendation actions and
  redact raw private values from receipts/traces.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_event_ingestion.py -q
ruff check services/discovery-api/app/events/ingestion.py services/discovery-api/tests/test_event_ingestion.py
git diff --check
```

## Commit

```text
feat(discovery): add consented interaction ingestion
```
