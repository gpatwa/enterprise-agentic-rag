# IMD-024: Index Maintenance and Alias Operations

## Objective

Add deterministic delete/tombstone, rebuild, reconciliation, and alias-swap
commands over a provider-neutral fake index. Dry-run, mismatch gates, rollback,
and deletion evidence must be explicit. Do not connect to live OpenSearch.

## Dependencies and Reads

- IMD-023 is merged; read the IMD-020 ADR, mapping, mapper, and worker.

## Owned Files

- Create `services/discovery-api/app/indexing/maintenance.py`.
- Create `services/discovery-api/tests/test_index_maintenance.py`.

## Requirements

- Model immutable generation aliases, tombstones, rebuild manifests, and
  reconciliation results with bounded counts/checksums.
- Require dry-run before destructive operations, reject count/checksum
  mismatches, and support deterministic rollback to the prior validated alias.
- Deleted/tombstoned IDs cannot reappear in rebuild output; no canonical data is
  mutated by the derived index operation.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_index_maintenance.py -q
ruff check services/discovery-api/app/indexing/maintenance.py services/discovery-api/tests/test_index_maintenance.py
git diff --check
```

## Commit

```text
feat(discovery): add index maintenance operations
```
