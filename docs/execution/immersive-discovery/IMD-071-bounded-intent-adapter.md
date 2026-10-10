# IMD-071: Scripted Fake and Bounded Intent Adapter

## Objective

Add a local-only provider boundary for optional discovery intent. Provider data
is untrusted and must pass the IMD-070 contract without changing deterministic
parser meaning or caller-owned context.

## Owned Files

- `services/discovery-api/app/intelligence/adapter.py`
- `services/discovery-api/tests/test_intent_adapter.py`

## Requirements

- Support deterministic scripted success, malformed, timeout, and
  injection-shaped provider outputs.
- Validate all provider output through `StructuredDiscoveryIntent`.
- Fall back to `build_intent` and `parse_query` semantics on provider error,
  timeout, malformed output, injection-shaped fields, or meaning changes.
- Keep model-off mode explicit when no provider is configured.
- Accept caller context only as an opaque mapping; never serialize, mutate, or
  use tenant, identity, safety, or eligibility fields.
- Do not wire routes, call a live model, call a network, or touch support or
  analytics products.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_intent_adapter.py -q
ruff check services/discovery-api/app/intelligence/adapter.py \
  services/discovery-api/tests/test_intent_adapter.py
git diff --check
```

## Commit

```text
feat(discovery): add bounded intent adapter
```
