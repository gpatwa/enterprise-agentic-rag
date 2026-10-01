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
- **Ontology (optional `ontology_source`):** `OntologyFileRefreshSource` reads an
  `OntologySnapshot` JSON (for example a Git checkout) each run and the worker
  embeds it in the published `ContextSnapshot`. Lifecycles pass through verbatim;
  nothing is promoted to `certified`. The graph is complete per fetch, so a node
  missing from it is removed (no tombstones); changes report node IDs and
  `edge:<id>`. Wrong-tenant or empty-after-populated fetches count as failures
  (the worker checks tenant itself, not just the source), a failure reuses the
  last good graph, and one older than `max_source_age` blocks publication
  (`stale ontology`). Provenance `observed_at` drift does not trigger a republish.
- Catalog assets without a revision get a content-digest `source_version` so
  provenance coverage stays verifiable.

## Evidence

- `services/analytics-api/tests/test_ads044_context_refresh.py` (22 tests) using
  the real dbt and OpenMetadata adapters over fake data and an
  `httpx.MockTransport`.

## Boundary

- No live OpenMetadata, dbt Cloud, or OpenSearch call was made; HTTP is faked.
  Live integration evidence remains a separate, explicitly-authorized gate.
- The resolution node reads the ontology through `SnapshotOntologyProvider`
  (`app/runtime/ontology_node.py`), an exact-ID, tenant-scoped read of the
  published snapshot that fails closed when the snapshot has no ontology. The
  graph is returned under the context snapshot's ID because the node pins
  ontology identity to the run's snapshot.
- **Run bootstrap:** `new_governed_run_state` (`app/runtime/run_start.py`) takes any
  `SnapshotSource` (the worker's `current_snapshot()`), selects the tenant's latest
  verified snapshot, and pins its ID in the initial `AgentRunState`. It refuses before
  any run exists (`SnapshotSelectionError`: `snapshot_unavailable`, `snapshot_stale`,
  `snapshot_tenant_mismatch`, `snapshot_has_no_ontology`, `purpose_not_authorized`).
  New runs float to newer snapshots; an existing run keeps its pinned ID across
  resume and replay. The bootstrap node remains the authoritative identity gate.
- Not wired: a production API caller of `new_governed_run_state` (ADS-045), and
  indexing the ontology in OpenSearch.
- The worker is a callable unit; scheduling/deployment is not included. State is
  a local atomic JSON file per tenant. Precedence-resolved source conflicts are
  reported (`resolved_conflicts`) but do not block; staleness and missing
  provenance do.
- Tombstones persist until the asset reappears. This does not change M1's
  pending human semantic-certification gate; refreshed assets are not certified
  by being published.
