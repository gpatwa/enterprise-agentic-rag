# ADS-015: Source Merge, Precedence, Conflicts, and Tombstones

Status: **Complete**
Milestone: M1
Depends on: ADS-012, ADS-013, ADS-014

## Deliverable

`packages/platform_contracts/context_merge.py` provides deterministic metadata
merging across Compass, dbt, OpenMetadata, PostgreSQL, and DuckDB evidence.
Provider precedence is explicit and stable. Conflicting scalar fields produce
structured conflict records naming every provider and the selected source;
non-conflicting lineage, ownership, tags, tests, exposures, and metrics are
combined deterministically.

Tombstones are explicit, versioned source facts. A tombstone from an equal or
higher-precedence source removes the asset from the merged snapshot, while a
lower-precedence deletion cannot erase higher-authority evidence.

## Evidence

- `packages/platform_contracts/tests/test_context_merge.py`
- Precedence, conflict reporting, higher-authority deletion, and lower-
  authority tombstone tests pass.

## Boundary

Merge output is context evidence. It does not certify a semantic contract,
grant data access, or build an OpenSearch index; those are later M1 gates.
