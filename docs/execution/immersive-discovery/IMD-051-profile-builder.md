# IMD-051: Versioned Short- and Long-Term Profile Builder

## Objective

Build deterministic consent-aware profiles from validated events. Capture
recency, explicit preference, negative feedback, and retention signals with
deletion-aware versioning and no raw history in responses.

## Dependencies and Reads

- IMD-018 and IMD-050 are merged.

## Owned Files

- Create `services/discovery-api/app/profiles/builder.py`.
- Create `services/discovery-api/tests/test_profile_builder.py`.

## Requirements

- Enforce tenant/user/as-of scope and consent; denied users receive a typed
  no-personalization profile.
- Separate short/long-term bounded features, recency decay, explicit
  preferences, negative feedback, retention, and profile version/checksum.
- Ignore future/replayed/deleted events and redact raw identifiers/history.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_profile_builder.py -q
ruff check services/discovery-api/app/profiles/builder.py services/discovery-api/tests/test_profile_builder.py
git diff --check
```

## Commit

```text
feat(discovery): add versioned profile builder
```
