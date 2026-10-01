# ADS-044: dbt/OpenMetadata Refresh and Snapshot Publication Worker

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M4
Depends on: ADS-016

## Deliverable

`services/analytics-api/app/context/refresh.py` adds `ContextRefreshWorker`,
whose `run_once()` fetches each `RefreshSource` (`ProviderRefreshSource` over any
metadata provider, `DbtArtifactRefreshSource` re-reading manifest/catalog/
run_results), merges by explicit precedence, applies the context quality gate,
and publishes an immutable `ContextSnapshot`.

- **Incremental:** per-source and per-asset content hashes (observation time
  excluded) yield added/updated/removed reports; unchanged content publishes
  nothing and only renews the verification clock.
- **Tombstones:** an asset a healthy source stops reporting (including HTTP 404)
  is tombstoned with its last source version and excluded; reappearance lifts it.
  A source that returns nothing after having data is treated as an outage, never
  mass deletion.
- **Failure:** a failing source keeps its last-good assets, is reported with a
  credential-free error, and does not renew verification. No source ever
  succeeding yields `failed`.
- **Staleness:** past `max_source_age`, reused assets are marked stale and the
  quality gate blocks publication. `current_snapshot()` fails closed with
  `StaleSnapshotError` when the pointer is unverified for `max_snapshot_age`,
  and `NoSnapshotError` when nothing is published.
- **Publication order:** registry publish, then an optional index hook (for
  `OpenSearchContextIndex.index_snapshot`), then the pointer. A hook failure
  leaves the pointer on the previous snapshot; the retry reuses the stored
  snapshot (same content hash, same ID).
- Catalog assets without a revision get a content-digest `source_version` so
  provenance coverage stays verifiable.

## Evidence

- `services/analytics-api/tests/test_ads044_context_refresh.py` (11 tests) using
  the real dbt and OpenMetadata adapters over fake data and an
  `httpx.MockTransport`.

## Boundary

- No live OpenMetadata, dbt Cloud, or OpenSearch call was made; HTTP is faked.
  Live integration evidence remains a separate, explicitly-authorized gate.
- The worker is a callable unit; scheduling/deployment is not included. State is
  a local atomic JSON file per tenant. Precedence-resolved source conflicts are
  reported (`resolved_conflicts`) but do not block; staleness and missing
  provenance do.
- Tombstones persist until the asset reappears. This does not change M1's
  pending human semantic-certification gate; refreshed assets are not certified
  by being published.
