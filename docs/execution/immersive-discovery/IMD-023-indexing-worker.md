# IMD-023: Bounded Outbox Indexing Worker

## Objective

Implement a provider-neutral bounded outbox indexing worker over the IMD-022
document mapper. It must support bulk upsert, retry, checkpoint, poison
record, and idempotency behavior through a fake provider. No live OpenSearch
connection or unbounded worker loop is allowed.

## Dependencies and Reads

- IMD-013 and IMD-022 are merged.
- Read persistence DTOs, the document mapper, mapping ADR, and IMD-006 fakes.

## Owned Files

- Create `services/discovery-api/app/indexing/__init__.py`.
- Create `services/discovery-api/app/indexing/worker.py`.
- Create `services/discovery-api/tests/test_indexing_worker.py`.

Do not edit mapper/mapping, persistence, API, Docker, cloud, support,
analytics, or web files.

## Requirements

- Define a small provider-neutral bulk-index protocol and deterministic fake.
- Enforce batch and attempt caps, exponential retry bounds, stable document
  IDs, idempotent upserts, explicit poison-record quarantine, and checkpoint
  advancement only for accepted records.
- Return redacted evidence with counts, failures, attempts, and checkpoint.
- Never swallow failures or claim an external index was updated.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_indexing_worker.py -q
ruff check services/discovery-api/app/indexing services/discovery-api/tests/test_indexing_worker.py
git diff --check
```

## Commit

```text
feat(discovery): add bounded indexing worker
```
