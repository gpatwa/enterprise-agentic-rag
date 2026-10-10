# IMD-022: Provider-Neutral Catalog Document Mapper

## Objective

Map authoritative immersive catalog records and approved derived signals into
the versioned OpenSearch document contract. The mapper must be deterministic,
exclude prohibited user/private fields, and preserve source, content, and
permission versions. Do not index, connect to OpenSearch, or alter mappings.

## Dependencies and Reads

- IMD-004 and IMD-021 are merged.
- Read the domain models, mapping contract, IMD-020 ADR, and canonical plan.

## Owned Files

- Create `services/discovery-api/app/search/mapper.py`.
- Create `services/discovery-api/tests/test_catalog_mapper.py`.

Do not edit `mapping.py`, domain models, repositories, workers, provider
clients, API, deployment, support, analytics, or web files.

## Requirements

- Produce a strict typed document with all required mapping fields and explicit
  schema/embedding/generation metadata.
- Normalize only approved searchable text and stable IDs; preserve authoritative
  values and approved derived signals without accepting user history or raw
  profile vectors.
- Reject missing provenance/content/permission versions, tenant mismatch,
  unsupported embedding dimensions, and blocked/invalid records.
- Serialize in stable key order and include a deterministic document ID.

## Acceptance and Validation

Tests cover mapping of a golden record, stable serialization, required metadata,
blocked/invalid input rejection, prohibited-field exclusion, and version
preservation.

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
pytest services/discovery-api/tests/test_catalog_mapper.py -q
ruff check services/discovery-api/app/search/mapper.py services/discovery-api/tests/test_catalog_mapper.py
git diff --check
```

## Commit

```text
feat(discovery): add catalog document mapper
```
