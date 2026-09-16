# ADS-017: OpenSearch Context Index

Status: **Complete**
Milestone: M1
Depends on: ADS-016

## Deliverable

`services/analytics-api/app/context/index.py` provides the
`OpenSearchContextIndex` adapter and its explicit mapping. Snapshot assets are
indexed as searchable context documents with tenant, snapshot, asset,
certification, lifecycle, provenance, and text fields.

Index creation uses the explicit mapping and bulk indexing uses OpenSearch's
newline-delimited bulk protocol. Document IDs include tenant, snapshot, and
asset identity so independent tenants and immutable snapshots cannot overwrite
one another.

The adapter owns the authorization-relevant query shape: every search is
filtered by the requested tenant and certified results are required by
default. Returned hits are rechecked against tenant scope before becoming
context-pack candidates. The client is injected so local tests can prove the
request contract without requiring a running OpenSearch cluster.

## Evidence

- `services/analytics-api/app/context/index.py`
- `services/analytics-api/tests/test_context_m1.py`
- `scripts/verify_context_local.py` via `make verify-context-local`
- Mapping and tenant/certification filter assertions pass.
- Live local OpenSearch 2.15 indexing and retrieval passed for two tenants.

## Boundary

This is the analytics context-index adapter, separate from the support search
service. It establishes the lexical serving contract; live OpenSearch cluster
drills, embedding ingestion, hybrid retrieval, and operational sign-off are
later integration work.
