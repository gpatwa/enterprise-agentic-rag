# Product Separation Proposal

Status: **Proposal.** Written by the implementing agent from the repository state on 2026-10-29 (`origin/main` at `910a1eb`). Nothing here is an approval, a commitment, or a recorded human gate. The owner adopts, amends, or rejects each item in their own words. No CI, deploy, or infrastructure change is made by this document.

## Goal

Run each product as its own deployable service, with its own CI and its own infrastructure, so that a change to one product cannot block or break another. Keep one repository and the shared `packages/platform_contracts` library for now.

## Current state (what the repository shows)

| Product | Frontend | Backend | Deployed today |
|---|---|---|---|
| Analytics (Compass) | `apps/analytics-web` | `services/analytics-api` | Yes, Azure pilot (Container Apps API, Static Web App) |
| Marketing site | `apps/landing` | none | Yes, Static Web App |
| Resolution Intelligence (support) | `apps/support-web` | `services/api` | No |
| Discovery | `apps/discovery-web` | `services/discovery-api` | No |
| Platform services | none | `services/control-plane`, `data-plane`, `gateway`, `sandbox` | No |

Shared library: `packages/platform_contracts` (used by all backends; not a deployable).

### Findings that shape the proposal

1. **CI is shared, not per product.**
   - `ci.yml` (backend) triggers on `services/api`, `services/analytics-api`, `services/control-plane`, `services/data-plane`, `packages/**`, `infra/**` and `pyproject.toml`. A support-API change therefore runs, and can fail, the Analytics jobs, and the reverse.
   - `ci-frontend.yml` covers `support-web`, `analytics-web` and `landing` in one workflow.
   - **No workflow covers `services/discovery-api` or `apps/discovery-web`.** I searched `.github` on `main` and found no reference to discovery. Its tests run only if someone runs them.
2. **`infra/**` triggers backend CI for every product**, including the Analytics Azure pilot stack.
3. **Terraform is already split in places:** `infra/terraform/azure-analytics-pilot` (Analytics pilot) is its own stack with its own state. The AWS files at the top of `infra/terraform` (`eks.tf`, `rds.tf`, `vpc.tf`, ...) belong to the older support/RAG platform. `azure`, `azure-dev` and `opensearch` are further stacks I have not reviewed.
4. **Deploy workflows:** `deploy-analytics-azure.yml`, `deploy-analytics-pilot-azure.yml` and `deploy-landing-azure.yml` are already product-specific. `deploy.yml`, `deploy-staging.yml` and `deploy-prod.yml` are older and not product-specific; I did not inspect what they target.
5. **Platform services coupling:** I found no Python import of `services/control-plane` or `services/data-plane` from `services/analytics-api`, `services/discovery-api` or `packages`. Analytics has its own `app/data_plane` package, which is a separate thing from the `services/data-plane` service. Whether `services/api` calls the control and data plane services over HTTP at runtime was **not traced**.
6. **Compose:** the single `docker-compose.yml` starts support, analytics, the data stores, monitoring and the control and data planes together. Discovery is absent.

## Proposal

### Principle
Split by deployable product. Do not split the repository yet: `platform_contracts` would need to be published and versioned across repositories, which is overhead with no customers.

### Step 1: CI and path boundaries (small, reversible, no deployed change)

Give each product its own backend and frontend workflow with its own path filter:

| Workflow | Paths that trigger it |
|---|---|
| `ci-analytics.yml` | `services/analytics-api/**`, `apps/analytics-web/**`, `packages/platform_contracts/**`, `infra/terraform/azure-analytics-pilot/**` |
| `ci-landing.yml` | `apps/landing/**` |
| `ci-support.yml` | `services/api/**`, `apps/support-web/**`, `packages/platform_contracts/**` |
| `ci-platform.yml` | `services/control-plane/**`, `services/data-plane/**`, `services/gateway/**`, `services/sandbox/**` |
| `ci-discovery.yml` (new) | `services/discovery-api/**`, `apps/discovery-web/**`, `packages/platform_contracts/**` |

Notes:
- A change to `packages/platform_contracts/**` intentionally runs every product that uses it. That is the point of the shared library.
- Existing workflow names, job names, and any branch-protection required checks must be mapped before the old files are removed, or merges will wait on checks that no longer exist. Required checks should be listed from repository settings first; I have not read them.
- Discovery's first workflow only runs its existing tests. Whether those tests pass on a clean machine has not been verified.

### Step 2: Infrastructure ownership

- Keep `infra/terraform/azure-analytics-pilot` as the Analytics stack and stop `infra/**` from triggering unrelated backend CI.
- Move or label the AWS files at `infra/terraform/*.tf` as the support/RAG platform stack (a folder rename plus a state-key check; no `terraform apply`).
- Do not create Terraform for Discovery now.

### Step 3: Platform services ownership (decision for the owner)

Decide where `control-plane`, `data-plane`, `gateway` and `sandbox` belong:

- **Option A (recommended):** they belong to Resolution Intelligence, because Analytics and Discovery do not import them. They get their own folder in CI (`ci-platform.yml`) but are deployed only when Resolution Intelligence is.
- **Option B:** keep them as a shared platform product with their own release cycle. This is more correct if several products will use them, and more work to run.

The runtime question in finding 5 should be answered before choosing.

### Step 4: Per-product deployment (only when a product is needed)

| Product | Deployment work | When |
|---|---|---|
| Analytics | Already done. Keep its workflow and Terraform stack. | Now |
| Landing | Already done. The GitHub workflow still needs the `AZURE_STATIC_WEB_APPS_API_TOKEN` secret, which only the owner can set. | Owner action |
| Resolution Intelligence | Own Dockerfile review, Terraform stack, pipeline, plus the platform services (Step 3). | When a support pilot is chosen |
| Discovery | A Dockerfile and a pipeline. Its own plan limits it to a local demo and forbids a cloud deploy. | Only on request |

### Out of scope
Splitting into separate repositories, publishing `platform_contracts` as a package, moving anything between Azure resource groups, changing any deployed service, and changing branch protection.

## Risks

- Narrow path filters can hide a break: a change to a shared file that is not listed will skip a product's CI. Mitigation: include `packages/platform_contracts/**` and shared test config in every list, and review the filters once after a week of use.
- Renaming workflows can leave required checks pending. Mitigation: list the required checks first and keep job names stable.
- Discovery's CI may fail on first run for reasons unrelated to the change.

## Decisions for the owner

1. Adopt Step 1 (per-product CI)? Yes / No / amend.
2. Platform services: Option A or B?
3. Should the older `deploy.yml`, `deploy-staging.yml` and `deploy-prod.yml` be retired? (Not inspected; they may be the only path for the legacy AWS stack.)
4. Is it acceptable to leave Discovery as a local demo, with CI only?

## Evidence not gathered

- Required status checks in repository settings.
- Contents and targets of `deploy.yml`, `deploy-staging.yml`, `deploy-prod.yml`, and the `azure`, `azure-dev` and `opensearch` Terraform stacks.
- Runtime calls from `services/api` to the control and data plane services.
- Whether Discovery's tests pass.

## Owner decisions (2026-10-29, recorded in the owner's words)

1. Per-product CI (Step 1): "yes".
2. Platform services: "Option A" (they belong to Resolution Intelligence).
3. Retiring `deploy.yml`, `deploy-staging.yml` and `deploy-prod.yml`: "don't retire ... it was meant for AWS deployment". They stay.
4. Discovery as a local demo with CI only: "No". Discovery is to become separately deployable. Its Dockerfile, CI and pipeline are follow-up work; a cloud deploy still needs a separate explicit request.

Follow-ups not in the first CI PR: Discovery CI (two tests failed in a clean environment and its `requirements.txt` lacks test dependencies), a CI workflow for the platform services (`control-plane`, `data-plane`, `gateway`, `sandbox`), which have had no CI since the shared `ci.yml` only ran the support tests.
