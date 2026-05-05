# Alpha — Azure Deploy Runbook

End-to-end runbook for the Compass internal-alpha deployment on Azure
(AKS + Postgres Flexible + Redis Cache + ACR + Key Vault).

Pair with [`ALPHA_OPS.md`](./ALPHA_OPS.md) (feedback / Sentry / uptime)
and [`ALPHA_LOOM_SCRIPT.md`](./ALPHA_LOOM_SCRIPT.md) (stakeholder demo).

---

## What you get

- A public URL (Azure LoadBalancer IP, http only) reachable from any
  browser.
- All in-app routes work: `/welcome`, `/`, `/sources`, `/threads`,
  `/saved`, `/agents`, `/dashboards`, `/knowledge`, `/solutions/*`.
- Feedback widget posts to `POST /api/v1/feedback` (Slack relay
  optional via `FEEDBACK_SLACK_WEBHOOK_URL`).
- Sentry capture optional via `SENTRY_DSN` / `VITE_SENTRY_DSN`.
- The DB is seeded with sample threads / saved questions / glossary
  (via `make seed-alpha`).

What is **not** wired yet (degrades gracefully):
- LLM provider — the agent's question-answering path returns errors
  until you set `OPENAI_API_KEY` (or wire Ray Serve). The UI tour still
  works; ask-flow is the one pre-condition.
- Vector / graph search — Qdrant / Neo4j aren't installed in the
  cluster (deferred to keep alpha lean). `/sources` shows them as
  "Error" or "not connected", which is correct.

---

## One-time setup

### 1. Provision infrastructure

```bash
cd infra/terraform/azure

# Generate fresh secrets locally (gitignored).
cat > terraform.tfvars <<EOF
db_password    = "$(python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(28)))')"
jwt_secret_key = "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
neo4j_password = "$(python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(20)))')"
openai_api_key = ""
environment    = "staging"
EOF

terraform init -reconfigure -backend-config="key=staging/terraform.tfstate"
terraform plan -out=tfplan-alpha
terraform apply tfplan-alpha
```

Provisions ~30 resources: AKS, ACR, Postgres Flexible Server, Redis
Basic, Key Vault, VNet, identities. **Total apply time: 20–30 min**
(Redis Basic SKU is the long pole at 15–20 min).

### 2. Wire OIDC for GitHub Actions deploys

Done once per repo. Lets `deploy-staging.yml` authenticate via federated
identity rather than long-lived secrets.

```bash
# Create app + SP
APP_ID=$(az ad app create --display-name "github-actions-compass-staging" --query appId -o tsv)
APP_OID=$(az ad app show --id "$APP_ID" --query id -o tsv)
SP_OID=$(az ad sp create --id "$APP_ID" --query id -o tsv)

# Federated credentials — one for environment-scoped jobs, one for branch-scoped
cat > /tmp/fed-staging.json <<EOF
{"name":"github-staging-env","issuer":"https://token.actions.githubusercontent.com",
 "subject":"repo:gpatwa/scalable-rag-pipeline:environment:staging",
 "audiences":["api://AzureADTokenExchange"]}
EOF
az ad app federated-credential create --id "$APP_OID" --parameters @/tmp/fed-staging.json

# Grant Contributor on the resource group
az role assignment create \
  --assignee-object-id "$SP_OID" --assignee-principal-type ServicePrincipal \
  --role Contributor \
  --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/rag-platform-rg"
```

### 3. Set GitHub repo secrets + variable

```bash
gh variable set CLOUD_PROVIDER --body "azure"
gh secret   set AZURE_CLIENT_ID         --body "$APP_ID"
gh secret   set AZURE_TENANT_ID         --body "$(az account show --query tenantId -o tsv)"
gh secret   set AZURE_SUBSCRIPTION_ID   --body "$(az account show --query id -o tsv)"
gh secret   set AZURE_RESOURCE_GROUP_STAGING --body "rag-platform-rg"
gh secret   set ACR_NAME                --body "ragplatformacr"
gh secret   set AKS_CLUSTER_NAME_STAGING --body "rag-platform-aks"

# After terraform apply finishes:
gh secret set API_IDENTITY_CLIENT_ID --body "$(cd infra/terraform/azure && terraform output -raw api_identity_client_id)"
```

Also create the `staging` GitHub environment (Settings → Environments
→ New) — the federated credential's `subject` is keyed on it.

### 4. Bootstrap the Kubernetes secret

The API pod reads `app-env-secret` for DB/Redis URLs etc. Create it
post-Terraform with:

```bash
./scripts/bootstrap_alpha_secret.sh
```

The script reads Terraform outputs + `terraform.tfvars`, generates the
`DATABASE_URL` and `REDIS_URL`, and applies the K8s secret idempotently.
Optional env vars threaded through:
- `FEEDBACK_SLACK_WEBHOOK_URL` — for B.1 Slack relay
- `SENTRY_DSN` — for B.3 backend error capture
- `MCP_ENCRYPTION_KEY` — if you want MCP enabled

### 5. Trigger first deploy

```bash
git push origin main
```

Watch in real time:
```bash
gh run watch
```

The workflow:
1. Runs pre-deploy tests (~30s)
2. Builds Docker image (Python + frontend) + pushes to ACR (~3 min)
3. Helm-upgrades to AKS (~2 min including LB IP allocation)

### 6. Capture the public IP

```bash
kubectl get svc api-service -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

Open `http://<that-ip>:8080/welcome` in a browser → you should see the
Compass landing page. `/` → in-app home. `/sources` → live infra +
App-connectors section.

### 7. Seed sample data (one-time)

The home page shows pinned questions + recent threads. Seed them:

```bash
# Get Postgres FQDN + password
cd infra/terraform/azure
PG_FQDN=$(terraform output -raw postgres_fqdn)
PG_PW=$(grep '^db_password' terraform.tfvars | sed 's/.*= *"\(.*\)"$/\1/')
cd ../../..

DATABASE_URL="postgresql://ragadmin:${PG_PW}@${PG_FQDN}:5432/ragdb?sslmode=require" \
  python3 scripts/seed_alpha.py
```

(SSL mode is required for Azure Postgres Flexible Server.)

---

## Day-to-day operations

### Putting the alpha to sleep (cost control)

The largest line items per month while running:
| Resource | ~$ / month |
|---|---|
| AKS system + app node pools (2× B-class burstable) | $60–80 |
| Postgres Flexible B1ms | $15 |
| Redis Basic C0 | $16 |
| LoadBalancer + public IP | $4 |
| ACR Basic | $5 |
| Storage account, Key Vault, VNet | $1 |
| **Total when running** | **~$100–120** |

To **pause** (stop incurring most of this) without destroying state:

```bash
# 1. Stop the AKS cluster — biggest cost line
az aks stop -g rag-platform-rg -n rag-platform-aks

# 2. Stop the Postgres server (preserves data)
az postgres flexible-server stop -g rag-platform-rg -n ragplatform-pgdb-central

# Redis Basic SKU does NOT support stop — leave it. ~$16/mo to keep it warm.
# Alternative: tear it down (see below) and recreate next time. ~15min cold start.
```

To **resume**:

```bash
az aks start -g rag-platform-rg -n rag-platform-aks
az postgres flexible-server start -g rag-platform-rg -n ragplatform-pgdb-central
# Wait ~5 min for kube nodes to be Ready, then:
kubectl rollout restart deployment/api-deployment
```

To **fully tear down** (zero ongoing cost, recreate from scratch later):

```bash
cd infra/terraform/azure
terraform destroy
# All data lost. Recreate via `terraform apply` + bootstrap script + seed.
```

### Updating the deployment

Push to main → workflow auto-deploys. Manual force re-deploy:

```bash
gh workflow run "Deploy Staging"
```

### Watching live logs

```bash
az aks get-credentials -g rag-platform-rg -n rag-platform-aks --overwrite-existing
kubectl logs -l app=api --tail=100 -f
```

### Rotating secrets

The DB password / JWT key / Neo4j password are stored both in Key Vault
(authoritative) and in the K8s `app-env-secret`. To rotate:

```bash
# 1. Generate new secret + update Key Vault
NEW_PW=$(python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(28)))')
az keyvault secret set --vault-name rag-platform-aks-kv --name db-password --value "$NEW_PW"

# 2. Update Postgres admin password
az postgres flexible-server update -g rag-platform-rg -n ragplatform-pgdb-central \
  --admin-password "$NEW_PW"

# 3. Re-run bootstrap to pick up the new value into K8s
DB_PASSWORD="$NEW_PW" ./scripts/bootstrap_alpha_secret.sh

# 4. Restart pods to read the new secret
kubectl rollout restart deployment/api-deployment
```

---

## Troubleshooting

### Pod is `CrashLoopBackOff` after deploy

Most common cause: `app-env-secret` doesn't exist or is missing fields.

```bash
kubectl describe pod -l app=api | grep -A5 "Events:"  # check container errors
kubectl get secret app-env-secret -o jsonpath='{.data}' | jq 'keys'  # which keys are set
```

If the secret is missing, run `./scripts/bootstrap_alpha_secret.sh`.

### Pod starts but `/health/readiness` returns 503

A dependency is unreachable. Check:
- Postgres firewall — must allow Azure services or pod IP
- Redis — TLS-only, port 6380, full key in URL
- Key Vault — pod's workload identity must be in the access policy
  (Terraform sets this up; if you ran `kubectl rollout` after a TF
  destroy + re-apply, the workload identity client ID may have rotated)

```bash
# Inside a debug pod:
kubectl exec deploy/api-deployment -- curl -s http://localhost:8080/health/deep | jq
```

### Public IP isn't being assigned to the LoadBalancer

```bash
kubectl get svc api-service -w
# If EXTERNAL-IP stays <pending> for >5 min, check AKS networking
kubectl describe svc api-service
```

### Cost is higher than expected

```bash
az consumption usage list --top 20 --query "[].{date:date, name:meterDetails.meterName, cost:pretaxCost}"
# Common surprises:
#   - LoadBalancer rules billed per-rule + per-MB egress
#   - Public IP retained from a stopped cluster (still billed)
#   - Log Analytics workspace ingesting at default rate
```

---

## Reference: file locations

| What | Where |
|---|---|
| Terraform | `infra/terraform/azure/` |
| Helm chart | `deploy/helm/api/` |
| Helm overlays | `values-azure.yaml` + `values-staging.yaml` |
| Dockerfile (multi-stage with frontend) | `services/api/Dockerfile` |
| Bootstrap script | `scripts/bootstrap_alpha_secret.sh` |
| Seed script | `scripts/seed_alpha.py` |
| Deploy workflow | `.github/workflows/deploy-staging.yml` |
| Backend env-vars source-of-truth | `services/api/app/config.py` |
| Frontend env-vars source-of-truth | `services/api/frontend/.env.example` |
