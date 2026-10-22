# Analytics pilot on Azure (Container Apps, low cost)

One governed API replica on Azure Container Apps, PostgreSQL Flexible Server (Burstable B1ms) for the control store and the pilot
warehouse, Key Vault for secrets, a Static Web App (Free) for the web UI, an hourly purge job, and an optional Azure OpenAI
`gpt-5.6-luna` deployment (reasoning effort medium) and Entra ID app registration. Separate state from the AKS platform in `../azure`.

Use this module when the AKS cluster in `../azure` is **not** already running. If it is, deploying the existing Helm charts
(`.github/workflows/deploy-analytics-azure.yml`, values updated for v2) adds almost nothing to the bill and is cheaper.

## Estimated monthly cost (East US, list prices, check the Azure pricing calculator before relying on them)

| Item | Choice | Approx. USD / month |
|---|---|---|
| Container App (API) | 0.5 vCPU / 1 GiB, 1 replica always on (idle billing applies when not serving) | 10 - 35 |
| Container Apps job (purge) | hourly, a few seconds each | < 1 |
| PostgreSQL Flexible Server | B1ms, 32 GiB storage, 7-day backups | 15 - 20 |
| Key Vault | standard, a few secrets | < 1 |
| Log Analytics | PerGB2018, 30-day retention, 1 GB/day cap | 0 - 10 |
| Container Registry | Basic (or reuse an existing one) | 0 - 5 |
| Static Web App | Free | 0 |
| Azure OpenAI | gpt-5.6-luna (medium), pay per token; cost per answer not yet measured (~4k in / 0.6k out per answer) | ~0.001 per answer |
| **Total** | | **about 30 - 70 + tokens** |

The `budget_emails` variable adds a resource-group budget with alerts at 80% and 100% of `monthly_budget_usd`.

Cost decisions: no AKS, no OpenSearch (context is built in-process from the certified registry), no VNet or private endpoints
(PostgreSQL uses TLS plus the "Azure services" firewall rule; tighten for production), Burstable database, one replica,
deterministic explanations (no second model call).

## Deploy (manual, about 30 minutes)

Prerequisites: Azure CLI logged in to the target subscription, Terraform >= 1.5, rights to create resources (and app
registrations if `create_entra_app = true`), the state storage account from `../azure/main.tf`.

1. `cd infra/terraform/azure-analytics-pilot`
2. `cp backend.hcl.example backend.hcl` and `cp terraform.tfvars.example terraform.tfvars`; edit both.
3. `./secrets.sh > secrets.auto.tfvars` (add `azure_openai_api_key = "..."` there if you use an existing Azure OpenAI).
4. Build and push the API image first (the Container App needs it):
   `az acr login -n <registry>`; from the repo root:
   `docker build --platform linux/amd64 -t <registry>/compass-analytics-api:<sha> -f services/analytics-api/Dockerfile . && docker push ...`
   (On the very first apply the registry does not exist yet: either set `existing_acr_login_server`, or apply once with
   `-target=azurerm_container_registry.acr`, push, then apply everything.)
5. `terraform init -backend-config=backend.hcl && terraform plan -out pilot.plan && terraform apply pilot.plan`
6. Bootstrap the warehouse role and sample data: see the header of `bootstrap.sql`.
7. Web: build `apps/analytics-web` with `VITE_ANALYTICS_API_URL=<api_url output>`, `VITE_ANALYTICS_API_KEY=<api_key>`,
   `VITE_ANALYTICS_DEFAULT_VIEW=governed`, and deploy `dist/` with the `static_web_app_deploy_token` output
   (`npx @azure/static-web-apps-cli deploy dist --deployment-token ...`), or run the workflow below.
8. Entra ID: assign users the `Analytics.Analyst` (and reviewers `Analytics.Reviewer`) app roles on the
   `<prefix>-<env>-analytics-api` enterprise application. A user gets a token with
   `az account get-access-token --scope <entra_audience>/.default --query accessToken -o tsv` (people only; an application identity with the `Analytics.ReviewAssistant` role may read reviews but the API gives it no purposes and never lets it decide) and pastes it in the web UI.
9. Check: `curl <api_url>/health` returns `ready` or `degraded` (the v1 LLM settings are not used by v2); ask a question in the
   web UI; `az containerapp logs show -n <app> -g <rg>`.

The workflow `.github/workflows/deploy-analytics-pilot-azure.yml` (manual dispatch only) builds and pushes the image, updates the
Container App, and deploys the web app.

## Operational notes

- Exactly one replica (`min = max = 1`). Do not scale out: quota state and the answer-row handoff are process-local.
- The API runs database migrations at start (`ANALYTICS_MIGRATE_ON_START`). A failed migration fails the revision, which keeps the
  previous one serving.
- Production refuses to start without `ANALYTICS_RUN_ID_KEY` (32+ bytes) and `ANALYTICS_API_KEY`; the legacy v1 query endpoint is
  off.
- `min_cohort = 10` follows the security persona's recommendation for finding F-03; changing it is the security owner's decision.
- Backups: PostgreSQL point-in-time restore (7 days). The logical backup and restore drill (ADS-068) can also be run against it.

## The review assistant (optional)

`python -m app.decision_support.agent --api <api_url> --token <token> --api-key <api_key>` lists pending reviews and prints one note per
review. Give its identity (for example a user-assigned managed identity) the `Analytics.ReviewAssistant` app role only. It is read-only
by construction: the API strips every other role from application tokens, and the decision endpoint needs the reviewer group and a
human caller. Never assign `Analytics.Reviewer` or `Analytics.Analyst` to an application.

## Notes from the first real deployment

- PostgreSQL Flexible Server provisioning is restricted in some regions per subscription (here `eastus`); `postgres_location` (default `centralus`) places it separately from the rest of the stack. Check with `az postgres flexible-server list-skus -l <region>`.
- The intent model is `gpt-5.6-luna` with `reasoning_effort=medium` (`azure_openai_*` variables). Reasoning models need `max_completion_tokens` and reject `temperature`, which `OpenAIStructuredClient` handles when `AZURE_OPENAI_REASONING_EFFORT` is set (requires the pinned `openai` SDK in `requirements.txt`).
- v2 Entra access tokens carry the app's **client id** as `aud`, so `ENTRA_AUDIENCE` is the client id, while users request the `api://.../.default` scope.
- The Azure CLI is pre-authorized for the `access_as_user` scope so `az account get-access-token` works for people holding an app role.
- The intent prompt now carries the certified vocabulary (ids only) and the query identity the model must echo; without them a real model cannot produce resolvable intents.
