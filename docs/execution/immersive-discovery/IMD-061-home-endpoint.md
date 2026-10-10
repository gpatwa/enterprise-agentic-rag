# IMD-061: Typed Personalized Home Endpoint

## Objective

Add a typed personalized-home route with persona/no-history modes, safe
diverse results, source/fallback evidence, consent-aware profiles, and
impression tokens.

## Dependencies and Reads

- IMD-037, IMD-052, and IMD-059 are merged; IMD-051 is available.

## Owned Files

- Create `services/discovery-api/app/routes/home.py`.
- Create `services/discovery-api/tests/test_home_endpoint.py`.

## Requirements

- Strict bounded request/response models with tenant/user/context/consent,
  persona, page size, versions, sources, reasons, and lineage tokens.
- Personalization denied/no-history modes use safe diverse fallback; hard
  eligibility is always enforced and private profile features are not returned.
- Use deterministic local orchestration and redacted fallback evidence.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_home_endpoint.py -q
ruff check services/discovery-api/app/routes/home.py services/discovery-api/tests/test_home_endpoint.py
git diff --check
```

## Commit

```text
feat(discovery): add personalized home endpoint
```
