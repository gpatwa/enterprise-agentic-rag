# IMD-069: API/Web End-to-End Discovery Journeys

## Objective

Add local end-to-end coverage for search, home, cold start, persona changes,
feedback adaptation, safety exclusion, and degraded-mode journeys. Tests must
use fictional deterministic data and no cloud/live model/OpenSearch services.

## Dependencies and Reads

- IMD-060 through IMD-068 are merged. Read only the discovery API/web app,
  local test fixtures, and existing test/build scripts.

## Owned Files

- Add Playwright/API E2E tests and local fixtures under the existing discovery
  app/test boundaries only.
- Add only the minimum local test configuration needed under the discovery
  product; do not edit root or support/analytics configuration.

## Requirements

- Cover search exact/natural/filter/no-result, home consent/no-history, persona
  switch, typed feedback adaptation, blocked/unsafe exclusion, fallback after
  provider failure, impression lineage, and redacted explanations.
- Assert bounded results, stable versions/reasons, no cross-tenant/private data,
  keyboard-accessible core flows, and deterministic repeatability.
- Keep tests runnable from a clean local seed and avoid deployment/network
  assumptions beyond local processes.

## Validation

```bash
npm --prefix apps/discovery-web run typecheck
npm --prefix apps/discovery-web test -- --run
npm --prefix apps/discovery-web run build
```

## Commit

```text
test(discovery): add api web end to end journeys
```
