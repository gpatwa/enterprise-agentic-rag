# Discovery pilot (Azure Container Apps)

The smallest footprint that serves the Discovery demo: a web Container App (public URL, Entra sign-in required) proxying `/api/` to an API Container App (internal ingress only). Both scale to zero. Plus an Entra app registration for sign-in, a Basic registry, Log Analytics (0.5 GB/day cap), a managed identity with `AcrPull`, and an optional budget alert.

No database, search cluster, model or secret: the API runs on fake providers over a seeded, fictional catalog (`DISCOVERY_ENVIRONMENT=staging`, `DISCOVERY_NO_MODEL=true`). Phase 2 (OpenSearch/PostgreSQL) is deliberately absent. See `docs/DISCOVERY_DEPLOYMENT_PROPOSAL.md`.

**Nothing here is applied by automation.** Applying it is a separate, explicit owner decision. It touches only the new `discovery-pilot-rg` resource group and its own state key.

## Access

Every request to the web app requires an Entra sign-in (Container Apps built-in authentication). The app registration has "assignment required" on, and `allowed_user_object_ids` lists the only accounts assigned to it: anyone else is refused after sign-in. The API has no public ingress.

- Get an object ID with `az ad user show --id <email-or-upn> --query id -o tsv`. A person outside the tenant must first be invited as a guest (Entra admin center → Users → Invite external user); use the object ID of that guest account.
- Revoke someone by removing their ID and re-applying (or by removing the assignment in the Entra portal).
- `allowed_cidrs` is an optional second layer. It is empty by default; `0.0.0.0/0` is rejected.
- The sign-in client secret is created by Terraform, held as a Container App secret and in state, and expires after 180 days; re-apply to rotate it.
- Applying needs rights to create app registrations in the tenant (Application Administrator or Owner of the new app is enough).

## Order of operations (when authorized)

1. Create the state backend config from `backend.hcl.example` (a state key of its own).
2. Create the registry first, then push both images, because the apps need an image to start:
   ```bash
   terraform init -backend-config=backend.hcl
   terraform apply -target=azurerm_container_registry.acr -var-file=terraform.tfvars
   ```
3. Build and push `discovery-api` (context: repo root, `services/discovery-api/Dockerfile`) and `discovery-web` (context: `apps/discovery-web`) with the tags set in `terraform.tfvars`.
4. `terraform apply -var-file=terraform.tfvars`, then open `web_url` and sign in with an assigned account.

A deploy workflow is not included yet.

## Local check (no Azure)

```bash
terraform init -backend=false && terraform validate && terraform fmt -check -recursive
```

CI runs the same three commands.

## Not verified

- A `terraform plan` or `apply` has never been run: the stack is only syntax- and schema-validated. That includes the sign-in pieces (app registration, role assignments, the `azapi` auth config).
- The Easy Auth redirect (`/.auth/login/aad/callback`) and the guest-account sign-in flow have not been tested.
- The web-to-API proxy over internal ingress (Host header, plain HTTP) is reasoned from Container Apps routing rules, not tested.
- Cost is not measured. The budget alert is set to the owner's chosen 25 USD.
