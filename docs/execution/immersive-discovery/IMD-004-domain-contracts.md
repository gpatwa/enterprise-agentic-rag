# IMD-004: Immersive Catalog, User, Context, and Eligibility Contracts

## Objective

Define the domain-owned models consumed by the immersive discovery product.
Separate authoritative catalog/profile fields from derived signals, compose
request-time context from the shared IMD-003 contract, and make eligibility a
deterministic fail-closed decision. This task does not add persistence, events,
OpenSearch, ranking, candidate sources, or API routes.

## Dependencies

- IMD-001 is merged at `e5c679d`.
- IMD-002 is merged at `676897d`.
- IMD-003 is merged at `1aebc9e`.
- The current branch contains the IMD-003 checkpoint.

## Read First

1. `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`
2. `docs/adr/ADR-IMD-001-immersive-discovery.md`
3. `docs/execution/immersive-discovery/IMD-004-domain-contracts.md`
4. `packages/platform_contracts/discovery.py`
5. `packages/platform_contracts/__init__.py`
6. `services/discovery-api/tests/fixtures/golden/experiences.json`
7. `services/discovery-api/tests/fixtures/golden/users.json`
8. `services/discovery-api/tests/fixtures/golden/policy_cases.json`

Do not read unrelated repository files.

## Owned Files

- Create `services/discovery-api/app/domain/models.py`.
- Create `services/discovery-api/tests/test_domain_models.py`.

Do not create package scaffolding beyond what Python namespace imports require.
Do not edit shared contracts, fixtures, persistence, event, search, ranking,
configuration, deployment, support, analytics, or web files.

## Contract Requirements

Define strict immutable Pydantic models for:

- authoritative `ExperienceRecord` fields represented in the golden catalog:
  stable experience/creator/tenant IDs, title/description, genres, themes,
  mechanics, supported devices/locales, age rating, safety state, availability,
  and synthetic/provenance markers;
- separate derived `ExperienceSignals` fields for freshness, quality,
  popularity, and any versioned derived score; derived fields must not be
  accepted as catalog truth;
- `UserProfile` fields represented in the golden users: stable user/tenant IDs,
  persona, locale, age-rating limit, devices, history-length, explicit
  preferences, consent state, and synthetic marker;
- request-time `ImmersiveDiscoveryContext` composed from the shared
  `DiscoveryRequestContext`, with bounded surface, optional seed experience,
  and typed filters;
- `EligibilityConstraints` and `EligibilityDecision` covering tenant, age,
  safety, locale, device, availability, consent/personalization mode, and a
  deterministic reason code.

Use explicit literals/enums, bounded strings and collections, tuples or other
immutable collections, `extra="forbid"`, and frozen models. Preserve the
fixture vocabulary without copying fixture JSON into production code. Reject
blank IDs, unsupported age/device/locale values, invalid age ordering, and
empty reason codes. Eligibility must fail closed when required context or
catalog fields are missing, tenant IDs differ, safety is restricted,
availability is false, age/device/locale constraints fail, or consent forbids
personalization. A model score must not be part of eligibility.

## Acceptance Evidence

- Domain models import with `PYTHONPATH="$PWD/services/discovery-api:$PWD"`.
- Representative golden experience and user records validate and round-trip
  deterministically without custom preprocessing.
- Authoritative records and derived signals are separate types and cannot be
  silently merged through extra fields.
- Context composes IMD-003 request identity without redefining or weakening it.
- Eligibility tests cover allow, tenant mismatch, age, safety, unavailable,
  locale, device, missing context, consent-denied personalization, and stable
  reason codes.
- Extra fields, blank IDs, invalid finite values, mutable-list mutation, and
  unsupported enum values are rejected.
- No persistence/provider/LLM/product API imports are introduced.
- The focused test and `git diff --check` pass without a running service.

## Targeted Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_domain_models.py -q
git diff --check
```

## Stop Conditions

Stop and report without editing other files if:

- IMD-003 is absent or its public names do not support composition;
- a fixture field requires deciding event, feature, or persistence ownership;
- eligibility would need a learned score, OpenSearch filter, or external policy
  service;
- the task would require changing the golden corpus or shared contract module.

## Commit

```text
feat(discovery): IMD-004 add immersive domain contracts
```

