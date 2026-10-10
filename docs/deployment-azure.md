# Azure Deployment Guide

Deploy the RAG platform to **Azure AKS** with PostgreSQL Flexible Server, Azure Cache for Redis, Blob Storage, and Key Vault.

The current staging deployment is recorded in
[`docs/execution/azure/AZURE-STAGING-DEPLOYMENT-2026-08-23.md`](execution/azure/AZURE-STAGING-DEPLOYMENT-2026-08-23.md).
It is a controlled demo deployment, not production approval.

## Public Landing Deployment

The public Compass landing page is deployed independently from AKS to Azure
Static Web Apps. Current production endpoint:

`https://red-pond-0fa9a940f.7.azurestaticapps.net`

The root route rewrites to the prerendered `/welcome` landing page. Rebuild
and publish it with:

```bash
./scripts/deploy_azure_landing.sh
```

The script obtains the Static Web Apps deployment token through Azure CLI and
does not store it in the repository. The manual GitHub Actions workflow
`Deploy Public Landing to Azure` provides the same path; configure the
production variable `PUBLIC_SITE_URL` and secret
`AZURE_STATIC_WEB_APPS_API_TOKEN` first. Add a custom domain in Azure Static
Web Apps after DNS ownership is available.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Azure CLI | 2.x | `brew install azure-cli` |
| Terraform | >= 1.5 | `brew install terraform` |
| kubectl | >= 1.28 | `brew install kubectl` |
| Helm | >= 3.12 | `brew install helm` |
| Docker | latest | [docker.com](https://docker.com) |

```bash
# Login and set subscription
az login
az account set --subscription "<SUBSCRIPTION_ID>"
```

---

## 1. Terraform State Backend

Create an Azure Storage Account for remote state:

```bash
RESOURCE_GROUP="rag-terraform-rg"
STORAGE_ACCOUNT="ragterraformstategp"
CONTAINER="tfstate"

az group create --name $RESOURCE_GROUP --location eastus
az storage account create --name $STORAGE_ACCOUNT --resource-group $RESOURCE_GROUP \
    --sku Standard_LRS --encryption-services blob
az storage container create --name $CONTAINER --account-name $STORAGE_ACCOUNT
```

Update `infra/terraform/azure/main.tf` backend block if your storage account name differs.

---

## 2. Provision Infrastructure

```bash
make infra-azure
# Equivalent to:
# cd infra/terraform/azure && terraform apply
```

### What Gets Created

| Resource | Dev/Staging | Production |
|----------|-------------|------------|
| AKS Cluster | Configured by `kubernetes_version` (currently v1.34), Standard LB | Same version policy, Standard LB |
| System Pool | Standard_B2s (1 node) | Standard_D2s_v5 (2+ nodes) |
| App Pool | Standard_B2s_v2 (1-3 auto) | Standard_D4s_v5 (2-6 auto) |
| PostgreSQL | Flexible Server, B_Standard_B1ms | D2s_v3, Zone Redundant HA |
| Redis | Azure Cache (Basic C0) | Premium P1 (clustering) |
| Blob Storage | Standard LRS | Standard GRS |
| Key Vault | Standard, soft-delete 7d | Standard, soft-delete 90d |
| ACR | Basic | Standard |

### Key Terraform Outputs

```bash
cd infra/terraform/azure
terraform output cluster_name
terraform output acr_login_server
terraform output postgres_fqdn
terraform output key_vault_url
terraform output api_identity_client_id
```

---

## 3. Workload Identity Setup

Azure Workload Identity replaces static credentials — pods authenticate to Azure services using federated tokens.

Terraform automatically:
1. Creates a User-Assigned Managed Identity for the API
2. Configures federated identity credentials for the `api-sa` service account
3. Grants Key Vault `Get` + `List` permissions to the identity
4. Grants ACR `AcrPull` to the AKS kubelet identity

The Helm chart creates the service account with the correct annotations:

```yaml
# values-azure.yaml (automatic)
serviceAccount:
  create: true
  name: api-sa
  annotations:
    azure.workload.identity/client-id: "<from terraform output>"
podLabels:
  azure.workload.identity/use: "true"
```

---

## 4. Key Vault Secrets

Terraform creates these secrets in Key Vault:

| Secret | Description |
|--------|-------------|
| `db-password` | PostgreSQL admin password |
| `jwt-secret-key` | JWT signing key |
| `redis-primary-key` | Redis auth token |
| `neo4j-password` | Neo4j database password |
| `openai-api-key` | OpenAI API key (if provided) |

The API fetches secrets at startup via `SECRETS_PROVIDER=azure_kv`:

```python
# Automatic at startup — no manual secret creation needed
settings.AZURE_KEY_VAULT_URL = "https://<vault-name>.vault.azure.net"
settings.SECRETS_PROVIDER = "azure_kv"
```

---

## 5. Bootstrap the Cluster

```bash
make bootstrap-azure
# Equivalent to:
# scripts/bootstrap_azure.sh
```

### Bootstrap Steps

1. **kubeconfig** — `az aks get-credentials`
2. **External Secrets Operator** — syncs Key Vault → K8s Secrets
3. **KubeRay Operator** — manages Ray clusters
4. **Qdrant** — vector database
5. **Neo4j** — graph database
6. **Ray Cluster** — head node + GPU workers
7. **NGINX Ingress** — load balancer; configure TLS before public production use
8. **API** — FastAPI backend with Workload Identity

AKS node pools use the native Azure Cluster Autoscaler configured in Terraform.
Karpenter manifests in this repository are AWS/EKS-specific and are not installed on AKS.
Qdrant and Neo4j are installed inside AKS with Azure Disk CSI-backed persistence.
OpenSearch is the enterprise search target, but its Terraform module is
provider-neutral and does not provision a managed service. Supply and validate
an approved OpenSearch endpoint before setting the API search provider to
OpenSearch; the current staging fallback remains Qdrant.

---

## 6. Build & Push Docker Image

```bash
make build-azure
# Equivalent to:
# ACR_NAME=$(terraform -chdir=infra/terraform/azure output -raw acr_login_server)
# az acr login --name $ACR_NAME
# docker build -t ${ACR_NAME}/rag-backend-api:$(git rev-parse --short HEAD) -f services/api/Dockerfile services/api
# docker push ${ACR_NAME}/rag-backend-api:$(git rev-parse --short HEAD)
```

---

## 7. Deploy API with Azure Values

The Azure deployment uses layered Helm values:

```bash
# Staging
helm upgrade --install api deploy/helm/api \
    -f deploy/helm/api/values-azure.yaml \
    -f deploy/helm/api/values-staging.yaml \
    --set image.repository=${ACR_NAME}/rag-backend-api \
    --set image.tag=$(git rev-parse --short HEAD) \
    --set "serviceAccount.annotations.azure\.workload\.identity/client-id=${CLIENT_ID}" \
    --set env.AZURE_KEY_VAULT_URL=${VAULT_URL}
```

### Values File Layering

```
values.yaml              (base defaults)
  └── values-azure.yaml  (Azure-specific: ACR, Workload Identity, Blob Storage)
        └── values-staging.yaml  (staging: 1 replica, DEBUG, LLM reranker)
        └── values-prod.yaml     (prod: 2 replicas, WARNING, cross-encoder)
```

### Azure-Specific Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `CLOUD_PROVIDER` | `azure` | Cloud selection |
| `STORAGE_PROVIDER` | `azure_blob` | Document storage |
| `SECRETS_PROVIDER` | `azure_kv` | Key Vault integration |
| `LLM_PROVIDER` | `openai` or `ray` | LLM backend |
| `EMBED_PROVIDER` | `openai` or `ray` | Embedding backend |
| `AZURE_KEY_VAULT_URL` | `https://...vault.azure.net` | Vault endpoint |

---

## 8. Verify Deployment

```bash
# Check pods
kubectl get pods

# Test health
kubectl port-forward svc/api-service 8080:80
curl http://localhost:8080/health/readiness

# Open Chat UI
open http://localhost:8080/
```

---

## 9. Cost Management

### Estimated Monthly Costs (Dev/Learning)

| Resource | Config | Est. Cost/mo |
|----------|--------|-------------|
| AKS Control Plane | Free tier | $0 |
| System Pool (B2s) | 1 node | ~$30 |
| App Pool (B2s_v2) | 1 node | ~$30 |
| PostgreSQL Flex (B1ms) | 1 vCore, 32GB | ~$25 |
| Redis (Basic C0) | 250MB | ~$16 |
| Blob Storage | minimal | ~$1 |
| Key Vault | Standard | ~$0.03/secret/mo |
| ACR (Basic) | 10GB | ~$5 |
| **Baseline (idle)** | | **~$107/mo** |

### Shutdown to Save Costs

```bash
# Scale workloads to zero
kubectl scale deploy --all --replicas=0
kubectl scale statefulset --all --replicas=0

# Stop AKS cluster (preserves config, stops billing for nodes)
az aks stop --name rag-platform-aks --resource-group rag-platform-rg

# Stop PostgreSQL
az postgres flexible-server stop --name rag-postgres --resource-group rag-platform-rg
```

---

## 10. Enable Optional Features

### Multimodal RAG (Gemini Embedding)

Store the Gemini API key in Key Vault via Terraform:

```hcl
# infra/terraform/azure/envs/staging.tfvars
gemini_api_key = "your-gemini-api-key"
```

Run `terraform apply` to store the secret, then re-bootstrap to inject it into the K8s secret. The feature is enabled by default in `values-staging.yaml` (`MULTIMODAL_ENABLED: "true"`).

### Context Layer Architecture

Enabled by default in staging. Seed initial context data after deployment:

```bash
# Port-forward to the API pod
kubectl port-forward svc/api-service 8080:80

# Seed glossary, business rules, code context
curl -X POST http://localhost:8080/api/v1/context/annotations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"annotation_type": "glossary", "key": "ARR", "value": "Annual Recurring Revenue"}'
```

### Analytics Product

Analytics now has independent API and web images under
`services/analytics-api` and `apps/analytics-web`. Deploy the two workloads
with the dedicated charts and script:

```bash
export ACR_NAME="<acr-name>"
export RESOURCE_GROUP="<resource-group>"
export CLUSTER_NAME="<aks-cluster>"
export ANALYTICS_HOSTNAME="analytics.example.com"
export ANALYTICS_API_IDENTITY_CLIENT_ID="$(terraform -chdir=infra/terraform/azure output -raw analytics_api_identity_client_id)"
kubectl apply -f deploy/secrets/analytics-external-secret-azure.yaml
./scripts/deploy_azure_analytics.sh
```

The script builds and pushes `compass-analytics-api` from the repository root
and `compass-analytics-web`, then installs `analytics-api` and `analytics-web`
Helm releases. The analytics API uses the `analytics-api-secrets` Kubernetes
Secret populated from Key Vault; create `analytics-db-url` and
`analytics-control-db-url` in Key Vault before rollout. The web chart proxies
`/api` and `/health` to the internal `analytics-api:8090` service and exposes
the configured hostname through the cluster ingress.

For GitHub Actions, use the manual `Deploy Analytics to Azure` workflow. It
requires OIDC secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AKS_CLUSTER_NAME`,
`ACR_NAME`, `ANALYTICS_API_IDENTITY_CLIENT_ID`, and `ANALYTICS_HOSTNAME`.

### Key Vault Secrets for Features

| Feature | Key Vault Secret | Terraform Variable | Required |
|---------|------------------|--------------------|----------|
| Multimodal | `gemini-api-key` | `gemini_api_key` | When MULTIMODAL_ENABLED=true |
| Web Search | `tavily-api-key` | `tavily_api_key` | When using web_search tool |
| OpenAI LLM | `openai-api-key` | `openai_api_key` | When LLM_PROVIDER=openai |

---

## 11. Subsequent Deploys

```bash
make build-azure        # Rebuild Docker image
make deploy-api-azure   # Helm upgrade
make deploy-analytics-azure # Build and deploy analytics API + web
```

---

## AWS vs Azure Comparison

| Concern | AWS | Azure |
|---------|-----|-------|
| Kubernetes | EKS + Karpenter | AKS + native Cluster Autoscaler |
| Database | Aurora Serverless v2 | PostgreSQL Flexible Server |
| Cache | ElastiCache Redis | Azure Cache for Redis |
| Storage | S3 | Blob Storage |
| Container Registry | ECR | ACR |
| Secrets | Secrets Manager + IRSA | Key Vault + Workload Identity |
| GPU Autoscaling | Karpenter SPOT | Ray autoscaling on AKS node pools; GPU pool provisioning remains deployment-specific |
| Free K8s Control Plane | No ($73/mo) | Yes (free tier) |

---

## Related Docs

- [Architecture & Design](architecture.md)
- [AWS Deployment](deployment-aws.md)
- [API Reference & Chat UI](api-reference.md)
- [Operations Guide](operations.md)
