# IMD-011: Validated Local Configuration and Feature Flags

## Objective

Define validated configuration for the independent discovery service. Local
fake/no-model operation must be explicit, unsafe production-like defaults must
fail validation, and feature flags must be typed and bounded. Do not add cloud
deployment, provider clients, persistence, search, or API routes beyond the
existing health scaffold.

## Dependencies and Reads

- IMD-010 is merged.
- Read the canonical execution plan, `services/discovery-api/app/main.py`,
  `services/discovery-api/requirements.txt`, and the IMD-001/020 ADRs.

## Owned Files

- Create `services/discovery-api/app/config.py`.
- Create `services/discovery-api/tests/test_config.py`.

Do not edit `main.py`, shared contracts, support/analytics services, Docker,
Azure, OpenSearch clients, or web files.

## Requirements

- Use strict Pydantic settings/models with explicit defaults safe for local use.
- Require a local environment/profile and explicit fake-provider/no-model flags.
- Validate bounded host/port, request limits, timeouts, candidate caps, and
  allowed environments; reject production mode without required safeguards.
- Parse no secrets into logs or serialized configuration.
- Provide deterministic feature flags for lexical, vector, hybrid, learned,
  and LLM paths, with model/LLM paths disabled by default.

## Acceptance

Tests cover local defaults, explicit fake mode, invalid production-like
settings, bounds, feature-flag combinations, and redacted serialization.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
pytest services/discovery-api/tests/test_config.py -q
ruff check services/discovery-api/app/config.py services/discovery-api/tests/test_config.py
git diff --check
```

## Commit

```text
feat(discovery): add validated local configuration
```
