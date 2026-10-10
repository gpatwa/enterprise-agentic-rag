# IMD-012: Provider-Neutral Repository Protocols

## Objective

Define bounded protocols for catalog, interaction-event, profile, and feature
repositories. Protocols express tenant-scoped domain operations without
provider SDK types or persistence decisions. Do not implement PostgreSQL,
OpenSearch, event-lake storage, API routes, or concrete adapters.

## Dependencies and Reads

- IMD-004, IMD-005, and IMD-010 are merged.
- Read the canonical execution plan, domain models, event models, and shared
  discovery contracts.

## Owned Files

- Create `services/discovery-api/app/repositories/__init__.py`.
- Create `services/discovery-api/app/repositories/protocols.py`.
- Create `services/discovery-api/tests/test_repository_protocols.py`.

Do not edit domain/event models, shared contracts, fakes, config, persistence,
search, deployment, support, analytics, or web files.

## Requirements

- Use `typing.Protocol` and provider-neutral domain types only.
- Expose bounded tenant-scoped reads/writes for catalog records, interaction
  events, user profiles, and derived features.
- Require pagination/limit bounds and explicit request identity where relevant.
- Keep authoritative records separate from derived projections and make event
  append semantics explicit without implementing storage.
- Include protocol conformance examples using tiny local test doubles.

## Acceptance

Tests verify runtime signatures through typed examples, bounded parameters,
tenant scope, separation of authoritative/derived records, and absence of
provider imports. Protocols remain implementation-independent.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
pytest services/discovery-api/tests/test_repository_protocols.py -q
ruff check services/discovery-api/app/repositories services/discovery-api/tests/test_repository_protocols.py
git diff --check
```

## Commit

```text
feat(discovery): define repository protocols
```
