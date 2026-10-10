# IMD-063: Independent React Discovery App Scaffold

## Objective

Scaffold `apps/discovery-web` as an independent local React app. It must
import neither support nor analytics product code and provide a minimal typed
API client/test/build configuration for later discovery workflows.

## Dependencies and Reads

- IMD-010 and IMD-060 through IMD-062 are merged.
- Read repository frontend conventions only as needed; keep this product
  boundary independent.

## Owned Files

- Create only files under `apps/discovery-web/` needed for package metadata,
  source entry, typed API client, test setup, and build configuration.
- Create focused tests under `apps/discovery-web/src/`.

Do not edit root package files, support/analytics apps, API services, cloud
deployment, or landing-page files.

## Requirements

- Use the existing local frontend toolchain if present; otherwise keep the
  smallest deterministic React/TypeScript scaffold.
- Include local-only API base configuration and typed request/response boundary.
- Typecheck, unit test, and production build must be runnable independently.
- Do not add external auth, model calls, remote media, or analytics imports.

## Validation

```bash
npm --prefix apps/discovery-web run typecheck
npm --prefix apps/discovery-web test -- --run
npm --prefix apps/discovery-web run build
```

## Commit

```text
feat(discovery-web): scaffold independent discovery app
```
