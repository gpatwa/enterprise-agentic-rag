# IMD-060: Typed Search Endpoint

## Objective

Add the typed discovery search route over query parsing, eligibility, candidate
retrieval, ranking, explanations, versions, and impression tokens. Invalid
context fails closed; responses are bounded and redacted.

## Dependencies and Reads

- IMD-028, IMD-029, and IMD-059 are merged.
- Read the FastAPI scaffold, shared contracts, query/policy/ranking modules,
  and candidate/retrieval response models.

## Owned Files

- Create `services/discovery-api/app/routes/__init__.py`.
- Create `services/discovery-api/app/routes/search.py`.
- Create `services/discovery-api/tests/test_search_endpoint.py`.

## Requirements

- Define strict request/response models with bounded query, context, page size,
  results, reason codes, component versions, and impression token lineage.
- Use deterministic local providers/fakes; preserve hard eligibility and stage
  fallback evidence; do not call cloud/model services.
- Keep raw query/profile vectors/private social data out of ordinary logs and
  responses. Invalid tenant/user/context fails closed with typed errors.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_search_endpoint.py -q
ruff check services/discovery-api/app/routes services/discovery-api/tests/test_search_endpoint.py
git diff --check
```

## Commit

```text
feat(discovery): add typed search endpoint
```
