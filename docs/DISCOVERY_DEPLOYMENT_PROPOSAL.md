# Discovery Deployment Proposal

Status: **Proposal.** Written by the implementing agent from the repository state on 2026-10-30 (`origin/main` at `6c81726`). Nothing here is an approval, a commitment, or a recorded human gate. The owner adopts, amends, or rejects each item in their own words. **No Azure resource is created, and no Terraform is applied, by this document or by adopting it.** A cloud deploy needs a separate explicit request in that task.

## Goal

Make Discovery (`services/discovery-api`, `apps/discovery-web`) separately deployable, as the owner decided on 2026-10-29 ("No" to keeping it a local demo). This proposal says what exists, what is missing, what a deployment would be built from, and in what order.

## Current state (what the repository shows)

| Piece | State |
|---|---|
| CI | `ci-discovery.yml` on `main`: API lint and tests, web type-check, tests and build, both Docker images built, API image `/health` checked. All passing. |
| Dockerfiles | Present for API (port 8110) and web (nginx proxying `/api/` to `DISCOVERY_API_HOST`). |
| API entrypoint | `services/discovery-api/app/main.py` serves **only `/health`**. |
| Routes | `app/routes/{search,home,interactions}.py` exist but are **not included** in the app. The web client calls `/api/discovery/search`, which the deployed API would return 404 for. |
| Data stores | The plan names PostgreSQL (catalog, events), OpenSearch (retrieval) and object storage (event lake). Nothing in the app reads connection settings for them yet: `settings_from_env` reads only `DISCOVERY_*` flags (environment, profile, port, feature flags). |
| Terraform | None for Discovery. |
| Deployed | No. |

### Blockers found while reading the code

1. **Production settings validation is inverted.** `DiscoverySettings` in `app/config.py` requires `auth_enabled`, `tls_enabled` and `audit_logging_enabled` to be `False` in `production` (the check flags any value that `is not False`). I ran it: a production config with all three **on** is rejected with "production requires real providers and auth, TLS, and audit safeguards", and one with all three **off** is accepted. The intent is evidently the opposite. This must be fixed, with a test, before any non-local environment is configured. Until then, only `staging` (which has no such check) or `local` can run.
2. **The app is a stub.** A deployed image would pass health checks and serve nothing else.
3. **Auth is not implemented as a flag-only matter.** `auth_enabled` is a setting; whether any route enforces it was not traced.
4. **Defaults are demo-only.** `fake_provider=True`, `no_model=True`: the service runs on generated, fictional data. Per the plan, generated behavior is demonstration data, not evidence of real engagement or lift.

## What the plan already forbids (and what changes it)

`docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md` says Luna may not approve "live experimentation, automated model promotion, or cloud deployment", and IMD-088 approves only a local demo. The owner's 2026-10-29 answer ("No" to local-demo-only) is the decision that opens this work, but **a cloud deployment itself remains a human gate** with its own go-ahead. Also still bound by the plan: fictional or licensed data only, no Roblox assets or branding claims, no customer behavioral data without a decision.

## Proposed approach

Reuse the pattern of the Analytics pilot stack (`infra/terraform/azure-analytics-pilot`: resource group, Container Apps environment, ACR, Key Vault, user-assigned identity, Log Analytics, Static Web App, budget) in a **new, separate stack** `infra/terraform/azure-discovery-pilot`, with its own state key. No shared state, no shared resource group, and no touching Analytics or any other resource group.

### Phase 0: make the service deployable (code only, no cloud)
1. Fix the production-settings inversion, with tests for both directions (on is accepted, off is rejected).
2. Mount `search`, `home` and `interactions` routers in `app/main.py` behind the existing fake providers, with tests that `/api/discovery/search` returns a valid response against the fixture catalog.
3. Decide how the demo catalog is loaded in a container (generated at start from a seed, baked into the image, or object storage). Smallest option: generate at start from the seed, which needs no store.
4. Add a local compose profile for Discovery (the plan's IMD-080) so the pair can be exercised together before any cloud step.

Exit evidence: CI green; `docker run` of both images serves a real search through the web proxy locally.

### Phase 1: minimal cloud footprint (needs the owner's go-ahead)
Smallest viable set, to keep cost low:
- Resource group `discovery-pilot-rg` (new, named for this product).
- Log Analytics workspace, Container Apps environment, one Container App for the API (1 replica, scale to zero allowed).
- Static Web App for `apps/discovery-web`.
- ACR (or reuse is **not** proposed; a separate registry keeps the stacks independent).
- Budget alert at a low cap, same pattern as Analytics (`monthly_budget_usd`).
- No PostgreSQL, OpenSearch or object storage in Phase 1: the fake-provider demo needs none. This is the main cost saving and the reason Phase 1 is small.

Public access: the Analytics demo mode needed rate limits and isolation because it calls a paid model. Discovery's demo runs with `no_model=True`, so it makes no paid model calls; a public demo would still need a request-rate limit and no personal data collection. Decide whether it is public or access-limited.

### Phase 2: real retrieval (only on request)
- OpenSearch (managed or self-hosted) and PostgreSQL, with persistence migrations from the plan's IMD-013 and the OpenSearch indexing packets. These are the expensive and operationally heavy parts; add them only when someone needs to see real hybrid retrieval, and cost them first.

### Deploy workflow
A manual `deploy-discovery-azure.yml` modeled on `deploy-analytics-azure.yml`: build and push images, then update the Container App and Static Web App. Triggered by hand only. It would need secrets that **only the owner sets**; I will not set GitHub secrets or print credentials.

## Cost (not measured)

I have no price data in this session and have not estimated a figure. Phase 1 uses Container Apps (consumption), a Static Web App, a registry and logs. The Analytics pilot's own bill is the best reference once read from Azure Cost Management. A budget alert is part of the stack, as it is for Analytics.

## Risks

- Deploying the current stub shows a "live" product that does nothing; Phase 0 avoids this.
- The inverted validation would, if "fixed" carelessly, ship a production profile with safeguards off. Hence the two-direction tests.
- A public demo of a Roblox-like catalog invites brand confusion. Keep the existing rule: fictional data, no Roblox branding or claims.
- Separate stack means duplicated baseline cost (registry, logs). Accepted for isolation; can be revisited if cost matters.

## Decisions for the owner

1. Adopt Phase 0 (code-only fixes and wiring, no cloud)? Yes / No / amend.
2. Phase 1 scope: the minimal footprint above, with no database or search cluster. Agree?
3. Public demo or access-limited?
4. Is a separate resource group and registry (full isolation) acceptable, versus sharing the Analytics registry?
5. Budget cap for the Discovery pilot (monthly USD).
6. When, if ever, to authorize the Azure deploy itself. Not requested now.

## Evidence not gathered

- Whether any route enforces `auth_enabled`.
- Real cost of the proposed footprint.
- Whether the web app works end to end against a mounted search route.
- Terraform provider and quota availability for a new resource group in the owner's subscription (the Analytics pilot needed PostgreSQL in a different region because the preferred region was restricted).
