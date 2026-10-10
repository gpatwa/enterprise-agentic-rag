# IMD-006: Deterministic Discovery Test Fakes

## Objective

Add in-memory repository, candidate-source, feature, and ranker fakes for
contract and integration tests. They must record bounded calls, simulate
failure and timeout, and preserve domain eligibility. Do not add production
providers, persistence, OpenSearch, model calls, or API routes.

## Dependencies and Reads

- IMD-004 and IMD-005 are merged.
- Read `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`,
  `services/discovery-api/app/domain/models.py`,
  `services/discovery-api/app/events/models.py`, and
  `packages/platform_contracts/discovery.py`.

## Owned Files

- Create `services/discovery-api/tests/fakes/__init__.py`.
- Create `services/discovery-api/tests/fakes/discovery.py`.
- Create `services/discovery-api/tests/test_fakes.py`.

Do not edit production modules, shared contracts, fixtures, configuration,
search, deployment, support, analytics, or web files.

## Requirements

- Use strict typed fakes with deterministic output and frozen configuration.
- Provide tenant-scoped catalog/profile reads, candidate-source results,
  feature hydration, and ranker results through small provider-neutral methods.
- Capture call inputs without storing raw secrets or unbounded payloads.
- Support explicit `failure` and `timeout` modes with deterministic exceptions.
- Return only eligible candidates and expose a call trace for tests.
- Keep all collections bounded and reject extra fields/blank identifiers.

## Acceptance

Tests cover deterministic repeatability, tenant isolation, eligibility
preservation, failure/timeout behavior, bounded calls, and captured traces.
No production dependency is introduced.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
pytest services/discovery-api/tests/test_fakes.py -q
ruff check services/discovery-api/tests/fakes services/discovery-api/tests/test_fakes.py
git diff --check
```

## Commit

```text
test(discovery): add deterministic discovery fakes
```
