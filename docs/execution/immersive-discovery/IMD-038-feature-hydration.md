# IMD-038: Online Point-in-Time Feature Hydration

## Objective

Hydrate ranking features for a request from versioned materialization output.
Missing or stale features must use typed defaults and expose version/age,
without leaking private attributes.

## Dependencies and Reads

- IMD-018 and IMD-037 are merged. Read feature materialization, candidate
  orchestration, and repository contracts.

## Owned Files

- Create `services/discovery-api/app/features/hydration.py`.
- Create `services/discovery-api/tests/test_feature_hydration.py`.

## Requirements

- Require tenant/request/as-of identity and a bounded feature allowlist.
- Reject future/stale/mismatched versions; apply typed defaults for missing
  values and record age/version metadata.
- Keep consent and privacy boundaries explicit; no raw history, vectors, or
  social identities in ordinary output or trace.
- Hydration is deterministic and provider-neutral.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_feature_hydration.py -q
ruff check services/discovery-api/app/features/hydration.py services/discovery-api/tests/test_feature_hydration.py
git diff --check
```

## Commit

```text
feat(discovery): add online feature hydration
```
