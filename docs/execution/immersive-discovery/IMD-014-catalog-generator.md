# IMD-014: Deterministic Fictional Catalog Generator

## Objective

Create a seedable generator and manifest for fictional immersive experiences,
users/personas, and related catalog metadata. The same seed must produce byte-
stable logical records and no PII or external data. Do not scrape Roblox,
download media, call models, or add runtime API behavior.

## Dependencies and Reads

- IMD-002 and IMD-004 are merged.
- Read the canonical plan, golden fixtures, domain models, and fixture-loader
  conventions.

## Owned Files

- Create `services/discovery-api/app/generation/__init__.py`.
- Create `services/discovery-api/app/generation/catalog.py`.
- Create `services/discovery-api/tests/test_catalog_generator.py`.

Do not edit golden fixtures, domain models, persistence, search, API, Docker,
support, analytics, or web files.

## Requirements

- Provide explicit demo and scale profiles with bounded counts and a seed.
- Generate valid domain records with stable IDs, creator distributions,
  locales/devices/age/safety coverage, provenance, and synthetic markers.
- Produce a manifest containing seed, profile, counts, distributions, and a
  checksum of canonical serialized records.
- Use deterministic ordering and avoid random values that are not seed-bound.

## Acceptance and Validation

Two runs with the same seed are byte-identical; different seeds differ;
generated records validate against IMD-004; profiles satisfy documented
minimums and contain no PII.

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
pytest services/discovery-api/tests/test_catalog_generator.py -q
ruff check services/discovery-api/app/generation services/discovery-api/tests/test_catalog_generator.py
git diff --check
```

## Commit

```text
feat(discovery): add deterministic catalog generator
```
