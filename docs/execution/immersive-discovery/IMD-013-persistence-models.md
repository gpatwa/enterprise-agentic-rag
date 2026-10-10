# IMD-013: Discovery Persistence Models and Baseline Migration

## Objective

Add local PostgreSQL-oriented authoritative persistence models and a baseline
migration for catalog records and canonical interaction events. Keep derived
features and OpenSearch projections separate. The migration must be reviewable
and locally testable without a running database; do not add API wiring,
indexing, cloud deployment, or support/analytics changes.

## Dependencies and Reads

- IMD-012 is merged; IMD-004 and IMD-005 are available.
- Read the execution plan, repository protocols, domain models, event models,
  and existing repository migration conventions only as needed.

## Owned Files

- Create `services/discovery-api/app/persistence/__init__.py`.
- Create `services/discovery-api/app/persistence/models.py`.
- Create `services/discovery-api/app/persistence/migrations/0001_discovery_baseline.sql`.
- Create `services/discovery-api/tests/test_persistence_models.py`.

Do not edit requirements, API routes, repositories, search, event lake,
Docker/Azure, support, analytics, or web files.

## Requirements

- Use strict provider-neutral persistence DTOs or SQLAlchemy-compatible models
  with explicit tenant keys, authoritative/derived separation, version fields,
  timestamps, consent/synthetic markers, and bounded JSON payloads.
- Make event identity and idempotency explicit; preserve append-only semantics.
- Include migration tables/constraints for catalog, profiles, events, and
  derived-version metadata without embedding OpenSearch state as authority.
- Ensure migration text is deterministic and contains no destructive reset.

## Acceptance and Validation

Tests cover round-trip validation, tenant/id uniqueness, timezone and version
requirements, event idempotency, and migration structure.

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
pytest services/discovery-api/tests/test_persistence_models.py -q
ruff check services/discovery-api/app/persistence services/discovery-api/tests/test_persistence_models.py
git diff --check
```

## Commit

```text
feat(discovery): add persistence models and baseline migration
```
