# ADS-013: dbt Mapping

Status: **Complete**
Milestone: M1
Depends on: ADS-010

## Deliverable

`DbtManifestProvider` accepts manifest, catalog, and optional run-results
artifacts. It normalizes model dependencies, column types and descriptions,
tests and test status, exposures, metrics, row-count quality, and artifact
checksums into the shared metadata model.

## Evidence

- `services/analytics-api/app/metadata/providers.py`
- `services/analytics-api/tests/test_metadata_providers.py`
- Pinned manifest/catalog/run-results fixture test passes.

## Boundary

dbt artifacts are source evidence. The adapter does not infer authorization or
promote a model to certified semantic status without the registry and merge
gates that follow in M1.
