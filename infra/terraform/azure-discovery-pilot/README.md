# Discovery pilot (Azure Container Apps)

The smallest footprint that serves the Discovery demo: a web Container App (public, address-limited) proxying `/api/` to an API Container App (internal ingress only). Both scale to zero. Plus a Basic registry, Log Analytics (0.5 GB/day cap), a managed identity with `AcrPull`, and an optional budget alert.

No database, search cluster, model or secret: the API runs on fake providers over a seeded, fictional catalog (`DISCOVERY_ENVIRONMENT=staging`, `DISCOVERY_NO_MODEL=true`). Phase 2 (OpenSearch/PostgreSQL) is deliberately absent. See `docs/DISCOVERY_DEPLOYMENT_PROPOSAL.md`.

**Nothing here is applied by automation.** Applying it is a separate, explicit owner decision. It touches only the new `discovery-pilot-rg` resource group and its own state key.

## Access

`allowed_cidrs` is required and must not be empty or allow all addresses. Only those ranges reach the web app; the API has no public ingress. This limits who can reach the demo; it is not user authentication. Anyone behind an allowed address can use it.

## Order of operations (when authorized)

1. Create the state backend config from `backend.hcl.example` (a state key of its own).
2. Create the registry first, then push both images, because the apps need an image to start:
   ```bash
   terraform init -backend-config=backend.hcl
   terraform apply -target=azurerm_container_registry.acr -var-file=terraform.tfvars
   ```
3. Build and push `discovery-api` (context: repo root, `services/discovery-api/Dockerfile`) and `discovery-web` (context: `apps/discovery-web`) with the tags set in `terraform.tfvars`.
4. `terraform apply -var-file=terraform.tfvars`, then open `web_url` from an allowed address.

A deploy workflow is not included yet.

## Local check (no Azure)

```bash
terraform init -backend=false && terraform validate && terraform fmt -check -recursive
```

CI runs the same three commands.

## Not verified

- A `terraform plan` or `apply` has never been run: the stack is only syntax- and schema-validated.
- The web-to-API proxy over internal ingress (Host header, plain HTTP) is reasoned from Container Apps routing rules, not tested.
- Cost is not measured. The budget alert is set to the owner's chosen 25 USD.
