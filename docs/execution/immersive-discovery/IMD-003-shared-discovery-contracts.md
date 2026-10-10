# IMD-003: Shared Discovery Envelopes and Version Primitives

## Objective

Define the small provider-neutral contract surface shared by future discovery
products. This task creates request context, component-version, impression
token, and decision-trace models only. It does not define immersive catalog
entities, interaction events, candidate sources, ranking features, or API
routes.

## Dependencies

- IMD-001 is merged at `e5c679d`.
- IMD-002 is merged at `676897d`.
- The current branch contains the Wave 0 checkpoint.

## Read First

1. `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`
2. `docs/adr/ADR-IMD-001-immersive-discovery.md`
3. `packages/platform_contracts/__init__.py`
4. `packages/platform_contracts/analytics_intent.py`
5. `packages/platform_contracts/analytics_planning.py`
6. `packages/platform_contracts/runtime.py`
7. `packages/platform_contracts/security.py`
8. `docs/execution/immersive-discovery/IMD-003-shared-discovery-contracts.md`

Do not read unrelated repository files.

## Owned Files

- Create `packages/platform_contracts/discovery.py`.
- Update `packages/platform_contracts/__init__.py` with only the new public
  exports.
- Create `services/discovery-api/tests/test_platform_contracts.py`.

Do not create the discovery service, domain models, event models, OpenSearch
types, ranking policy, database code, or UI code.

## Contract Requirements

Define strict, immutable Pydantic models for:

- request context with non-empty tenant, principal, request, purpose, locale,
  device, age, consent, and bounded group/context fields;
- a component version that can identify schema, artifact/model, and digest
  without importing a provider SDK;
- an impression token that binds a served request to its tenant and request,
  issuance/expiry, schema, and component versions;
- a decision trace that binds request/tenant identity to bounded stage and
  component-version evidence without raw query text, user history, vectors, or
  provider payloads.

Use explicit enums/literals for finite values, bounded strings/collections,
timezone-aware timestamps, `extra="forbid"`, and frozen models. Preserve
deterministic serialization and avoid mutable defaults. Keep the contract
provider-neutral so both immersive and future verticals can consume it.

## Acceptance Evidence

- All four models import from `packages.platform_contracts`.
- Valid examples round-trip through Pydantic serialization deterministically.
- Missing/empty tenant or principal, invalid finite values, oversized
  collections, naive timestamps, and extra fields are rejected.
- Frozen instances reject mutation.
- Impression tokens cannot cross tenant/request identity, and trace evidence
  cannot contain raw query, history, vector, or provider payload fields.
- The focused tests pass without a running service, database, OpenSearch, model,
  network, or new dependency.
- No discovery domain, analytics, or support module is imported by the shared
  contract module.
- `git diff --check` passes.

## Targeted Validation

```bash
PYTHONPATH="$PWD" pytest services/discovery-api/tests/test_platform_contracts.py -q
git diff --check
```

## Stop Conditions

Stop and report without editing other files if:

- IMD-001 or IMD-002 is absent from the current branch;
- an existing shared discovery contract conflicts with this scope;
- satisfying a requirement would require adding catalog, event, ranking, or
  provider-specific fields to the shared package;
- Pydantic behavior requires a dependency or configuration change outside the
  owned files.

## Commit

```text
feat(discovery): IMD-003 add shared discovery contracts
```

