# IMD-016: Provenance-Gated Catalog Adapter

## Objective

Define a provider-neutral public catalog adapter contract and implement one
fictional fixture adapter. Provenance, license, retrieval metadata, and source
identity must be explicit; unknown provenance fails closed and network access
is disabled by default.

## Dependencies and Reads

- IMD-004 and IMD-012 are merged.
- Read the execution plan, domain models, repository protocols, and golden
  fixtures. Do not browse or fetch external catalog data.

## Owned Files

- Create `services/discovery-api/app/adapters/__init__.py`.
- Create `services/discovery-api/app/adapters/catalog.py`.
- Create `services/discovery-api/tests/test_catalog_adapter.py`.

Do not edit domain models, repositories, fixtures, persistence, search, API,
deployment, support, analytics, or web files.

## Requirements

- Use typed adapter/provenance models with source type, source ID, license or
  provenance reference, retrieved-at, content version, and synthetic flag.
- Provide a fixture-only adapter over explicit local records.
- Reject missing/unknown provenance, tenant mismatches, and non-synthetic
  records when local fixture mode requires synthetic content.
- Make network access impossible in the fixture implementation and keep output
  bounded and deterministic.

## Acceptance and Validation

Tests cover valid fixture reads, provenance rejection, tenant scope, metadata
preservation, bounded limits, deterministic order, and no network imports.

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
pytest services/discovery-api/tests/test_catalog_adapter.py -q
ruff check services/discovery-api/app/adapters services/discovery-api/tests/test_catalog_adapter.py
git diff --check
```

## Commit

```text
feat(discovery): add provenance-gated catalog adapter
```
