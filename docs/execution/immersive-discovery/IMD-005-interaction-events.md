# IMD-005: Versioned Interaction-Event Contracts

## Objective

Define deterministic, versioned interaction events for immersive discovery.
Events must preserve impression lineage, tenant/user/item identity, consent,
synthetic provenance, event time, and typed action payloads. This task defines
the contract only; it does not persist, ingest, simulate, or materialize events.

## Dependencies

- IMD-003 is merged at `1aebc9e`.
- IMD-004 is merged at `ad90e75`.
- The current branch contains the IMD-004 checkpoint.

## Read First

1. `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`
2. `docs/adr/ADR-IMD-001-immersive-discovery.md`
3. `packages/platform_contracts/discovery.py`
4. `services/discovery-api/app/domain/models.py`
5. `services/discovery-api/tests/fixtures/golden/queries.json`
6. `services/discovery-api/tests/fixtures/golden/policy_cases.json`
7. `docs/execution/immersive-discovery/IMD-005-interaction-events.md`

Do not read unrelated repository files.

## Owned Files

- Create `services/discovery-api/app/events/models.py`.
- Create `services/discovery-api/tests/test_event_models.py`.

Do not add persistence, outbox, simulator, API routes, feature jobs, provider
types, database code, or UI code.

## Contract Requirements

Define strict immutable models for:

- a bounded typed event envelope with event ID/version/type, tenant/user/
  experience IDs, occurred-at timestamp, synthetic marker, consent state, and
  optional impression-token lineage;
- typed payloads for impression, click, detail view, play, qualified play,
  playtime, save, dismiss, report, invite, co-play, return, and retention;
- an explicit organic/direct-navigation event path when no impression token is
  valid, without allowing recommendation actions to bypass lineage;
- an event batch with deterministic ordering and bounded size.

Use the shared `ImpressionToken` and domain enums where appropriate. Require a
tenant and user match between event identity and token when lineage is present.
Require positive durations for playtime and qualified play, finite numeric
values, timezone-aware event times, stable IDs, and `synthetic: true` for
generated fixtures. Reject generic untyped payload dictionaries, extra fields,
future event versions, blank IDs, and action events without valid lineage.

## Acceptance Evidence

- Every required event type has a typed payload and stable serialization.
- Impression and recommendation actions require an impression token; organic
  navigation is explicitly typed and cannot masquerade as a recommendation.
- Token tenant/user/request binding is validated before accepting an event.
- Synthetic marker, consent state, timestamps, durations, and numeric bounds are
  validated.
- Batches reject duplicates, oversized collections, and non-deterministic order.
- Extra fields, blank IDs, naive timestamps, unsupported event types, and
  invalid payload/type combinations are rejected.
- Focused tests pass without persistence, network, OpenSearch, or a model.
- No support, analytics, provider, or database imports are introduced.
- `git diff --check` passes.

## Targeted Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_event_models.py -q
git diff --check
```

## Stop Conditions

Stop if the implementation would require deciding event persistence, simulator
probabilities, feature schemas, or a new shared contract outside the owned
files.

## Commit

```text
feat(discovery): IMD-005 add interaction event contracts
```

