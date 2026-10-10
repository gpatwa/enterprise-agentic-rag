# IMD-017: Append-Only Local Event Lake

## Objective

Add a local append-only event-lake writer and partition manifest. Writes must
be idempotent, partitioned, synthetic-labeled, checksum-recorded, and readable
without the API. Do not add cloud storage, streaming infrastructure, or
production deployment.

## Dependencies and Reads

- IMD-005, IMD-012, and IMD-015 are merged.
- Read event models, repository protocols, simulator output, and the plan.

## Owned Files

- Create `services/discovery-api/app/event_lake/__init__.py`.
- Create `services/discovery-api/app/event_lake/writer.py`.
- Create `services/discovery-api/tests/test_event_lake.py`.

## Requirements

- Write canonical JSONL partitions by tenant/date/event type with stable order.
- Reject non-synthetic records in local mode, duplicate event IDs, and
  cross-tenant batches; preserve event immutability.
- Emit a manifest with counts, byte sizes, checksums, schema version, and
  partition paths. Provide bounded read-back.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_event_lake.py -q
ruff check services/discovery-api/app/event_lake services/discovery-api/tests/test_event_lake.py
git diff --check
```

## Commit

```text
feat(discovery): add append-only local event lake
```
