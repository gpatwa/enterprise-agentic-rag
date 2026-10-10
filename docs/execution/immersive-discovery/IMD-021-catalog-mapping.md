# IMD-021: Versioned Immersive Catalog Mapping

## Objective

Define the versioned OpenSearch catalog mapping contract and a compatibility
checker. The mapping must support exact IDs, analyzed text, tags, locale,
device, age, safety, availability, vectors, provenance, and generation
aliases. This task is contract/configuration work only: do not connect to a
live OpenSearch cluster or implement indexing.

## Dependencies and Reads

- IMD-004 and IMD-020 are merged.
- Read the canonical execution plan, `docs/adr/ADR-IMD-020-immersive-catalog-search.md`,
  the IMD-004 domain models, and the OpenSearch mapping patterns under
  `services/search` only as needed.

## Owned Files

- Create `services/discovery-api/app/search/__init__.py`.
- Create `services/discovery-api/app/search/mapping.py`.
- Create `services/discovery-api/tests/test_catalog_mapping.py`.

Do not edit OpenSearch enterprise-search modules, domain models, repositories,
index workers, Docker, cloud files, support, analytics, or web files.

## Requirements

- Represent schema, embedding, analyzer, and generation versions explicitly.
- Generate deterministic mapping/settings structures with strict field types.
- Include keyword identity fields, analyzed search fields, hard eligibility
  filters, provenance/content versions, freshness/diversity fields, and a
  versioned 384-dimensional cosine vector contract.
- Implement compatibility checking that rejects changed dimensions, similarity,
  field types, required fields, analyzer versions, or incompatible generations.
- Model read/write aliases without mutating external state.

## Acceptance

Tests cover required fields, exact-vs-text field types, vector dimensions,
version metadata, compatible mappings, each incompatible change, and stable
serialized output. No provider SDK or network access is introduced.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
pytest services/discovery-api/tests/test_catalog_mapping.py -q
ruff check services/discovery-api/app/search services/discovery-api/tests/test_catalog_mapping.py
git diff --check
```

## Commit

```text
feat(discovery): add versioned catalog mapping
```
