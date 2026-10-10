# ADS-012: OpenMetadata Mapping

Status: **Complete**
Milestone: M1
Depends on: ADS-010

## Deliverable

The OpenMetadata adapter normalizes table metadata into the shared model,
including lineage, glossary terms, quality signals, freshness expectations,
classification tags, ownership, certification, and columns. HTTP transport is
injectable so conformance tests use pinned local fixtures.

## Evidence

- `services/analytics-api/app/metadata/providers.py`
- `services/analytics-api/tests/test_metadata_providers.py`
- Rich lineage, glossary, quality, freshness, and classification fixture test
  passes.

## Boundary

The provider is read-only and does not treat catalog metadata as certified
semantic truth until a later merge and certification milestone.
