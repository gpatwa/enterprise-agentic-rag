# ADS-033: Bounded Context Retrieval Node

Status: **Complete**
Milestone: M3
Depends on: ADS-018, ADS-030

## Deliverable

The retrieval handler loads the exact tenant-scoped immutable snapshot, asks
the search adapter only for certified documents from that snapshot, and builds
a deterministic context pack with one-hop certified ontology expansion. Both
candidate count and token budget are bounded by run policy. Snapshot citations
are checked before model use; mismatches fail closed.

`ContextSnapshotRegistry` stores immutable local snapshots by tenant and ID.
`OpenSearchContextIndex.search` accepts a snapshot filter in addition to the
tenant and certification filters.

## Evidence

- `services/analytics-api/app/context/snapshot_registry.py`
- `services/analytics-api/app/context/index.py`
- `services/analytics-api/app/runtime/context_node.py`
- Static validation: Ruff and `git diff --check` pass.

## Boundary

Snapshot ingestion/bootstrap wiring and live OpenSearch evidence remain
separate operational work. The handler accepts providers; it does not start a
manual indexing workflow or bypass OpenSearch ACL filters.
