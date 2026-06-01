#!/bin/bash
# scripts/bootstrap_cluster_azure.sh
# Bootstraps the AKS cluster with all required K8s resources.
# Run this AFTER terraform apply has provisioned the Azure infrastructure.
#
# Azure equivalent of scripts/bootstrap_cluster.sh (AWS EKS).
# Key differences: no Karpenter (AKS has built-in autoscaler), Workload Identity
# (not IRSA), ACR pull is handled via Terraform role assignment.

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-rag-platform-aks}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rag-platform-rg}"
ACR_NAME="${ACR_NAME:-ragplatformacr}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "  AKS Cluster Bootstrap"
echo "========================================"
echo "  Cluster:  $CLUSTER_NAME"
echo "  RG:       $RESOURCE_GROUP"
echo "  ACR:      $ACR_NAME"
echo "========================================"

# -----------------------------------------------------------
# 1. Configure kubectl
# -----------------------------------------------------------
echo ""
echo "Step 1: Getting AKS credentials..."
az aks get-credentials --resource-group "$RESOURCE_GROUP" --name "$CLUSTER_NAME" --overwrite-existing
kubectl cluster-info

# -----------------------------------------------------------
# 2. Create Kubernetes Secrets
# -----------------------------------------------------------
echo ""
echo "Step 2: Creating app-env-secret..."

# Get Terraform outputs
cd "$PROJECT_DIR/infra/terraform/azure"
POSTGRES_FQDN=$(terraform output -raw postgres_fqdn 2>/dev/null || echo "")
REDIS_HOST=$(terraform output -raw redis_hostname 2>/dev/null || echo "")
REDIS_PORT=$(terraform output -raw redis_ssl_port 2>/dev/null || echo "6380")
REDIS_KEY=$(terraform output -raw redis_primary_key 2>/dev/null || echo "")
STORAGE_ACCOUNT=$(terraform output -raw storage_account_name 2>/dev/null || echo "")
API_IDENTITY_CLIENT_ID=$(terraform output -raw api_identity_client_id 2>/dev/null || echo "")
KEY_VAULT_URL=$(terraform output -raw key_vault_url 2>/dev/null || echo "")
cd "$PROJECT_DIR"

# Fetch optional API keys from Key Vault (if configured)
GOOGLE_API_KEY="${GOOGLE_API_KEY:-}"
TAVILY_API_KEY="${TAVILY_API_KEY:-}"
if [ -n "$KEY_VAULT_URL" ]; then
    KV_NAME=$(echo "$KEY_VAULT_URL" | sed 's|https://||;s|\.vault.*||')
    GOOGLE_API_KEY=$(az keyvault secret show --vault-name "$KV_NAME" --name "gemini-api-key" --query "value" -o tsv 2>/dev/null || echo "")
    TAVILY_API_KEY=$(az keyvault secret show --vault-name "$KV_NAME" --name "tavily-api-key" --query "value" -o tsv 2>/dev/null || echo "")
    echo "  Fetched API keys from Key Vault: ${KV_NAME}"
fi

# Read DB password from tfvars (or prompt)
DB_PASSWORD="${DB_PASSWORD:-}"
if [ -z "$DB_PASSWORD" ]; then
    read -sp "Enter PostgreSQL password: " DB_PASSWORD
    echo ""
fi

read_tfvar() {
    local key="$1"
    awk -F= -v key="$key" '
        $1 ~ "^[[:space:]]*" key "[[:space:]]*$" {
            value=$0
            sub(/^[^=]*=/, "", value)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            gsub(/^"|"$/, "", value)
            print value
            exit
        }
    ' "$PROJECT_DIR/infra/terraform/azure/terraform.tfvars" 2>/dev/null || true
}

NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"
if [ -z "$NEO4J_PASSWORD" ]; then
    NEO4J_PASSWORD="$(read_tfvar neo4j_password)"
fi
if [ -z "$NEO4J_PASSWORD" ]; then
    NEO4J_PASSWORD="$(kubectl get secret app-env-secret -o jsonpath='{.data.NEO4J_PASSWORD}' 2>/dev/null | base64 -d 2>/dev/null || true)"
fi
if [ -z "$NEO4J_PASSWORD" ]; then
    NEO4J_PASSWORD="$(openssl rand -hex 24)"
fi

DATABASE_URL="postgresql+asyncpg://ragadmin:${DB_PASSWORD}@${POSTGRES_FQDN}:5432/ragdb"
REDIS_URL="rediss://:${REDIS_KEY}@${REDIS_HOST}:${REDIS_PORT}/0"

SECRET_ARGS=(
    --from-literal=DATABASE_URL="$DATABASE_URL"
    --from-literal=REDIS_URL="$REDIS_URL"
    --from-literal=JWT_SECRET_KEY="$(openssl rand -hex 32)"
    --from-literal=NEO4J_PASSWORD="$NEO4J_PASSWORD"
    --from-literal=AZURE_STORAGE_ACCOUNT_NAME="$STORAGE_ACCOUNT"
    --from-literal=CLOUD_PROVIDER="azure"
    --from-literal=STORAGE_PROVIDER="azure_blob"
    --from-literal=SECRETS_PROVIDER="azure_kv"
)
[ -n "$KEY_VAULT_URL" ] && SECRET_ARGS+=(--from-literal=AZURE_KEY_VAULT_URL="$KEY_VAULT_URL")
[ -n "$GOOGLE_API_KEY" ] && SECRET_ARGS+=(--from-literal=GOOGLE_API_KEY="$GOOGLE_API_KEY")
[ -n "$TAVILY_API_KEY" ] && SECRET_ARGS+=(--from-literal=TAVILY_API_KEY="$TAVILY_API_KEY")

kubectl create secret generic app-env-secret \
    "${SECRET_ARGS[@]}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "  Secret app-env-secret created/updated"

# -----------------------------------------------------------
# 3. Install KubeRay Operator
# -----------------------------------------------------------
echo ""
echo "Step 3: Installing KubeRay Operator..."
helm repo add kuberay https://ray-project.github.io/kuberay-helm/ 2>/dev/null || true
helm repo update
helm upgrade --install kuberay-operator kuberay/kuberay-operator \
    --version 1.0.0 \
    --wait

# -----------------------------------------------------------
# 4. Deploy Qdrant (Vector Database)
# -----------------------------------------------------------
echo ""
echo "Step 4: Deploying Qdrant..."
helm repo add qdrant https://qdrant.to/helm 2>/dev/null || true
helm repo update
QDRANT_VALUES_FILE="${QDRANT_VALUES_FILE:-deploy/helm/qdrant/values-azure.yaml}"
QDRANT_VALUES_ARGS=(--values deploy/helm/qdrant/values.yaml)
if [ -f "$QDRANT_VALUES_FILE" ]; then
    QDRANT_VALUES_ARGS+=(--values "$QDRANT_VALUES_FILE")
fi
helm upgrade --install qdrant qdrant/qdrant \
    --namespace default \
    "${QDRANT_VALUES_ARGS[@]}" \
    --wait --timeout 120s

# -----------------------------------------------------------
# 5. Deploy Neo4j (Graph Database)
# -----------------------------------------------------------
echo ""
echo "Step 5: Deploying Neo4j..."
helm repo add neo4j https://helm.neo4j.com/neo4j 2>/dev/null || true
helm repo update
NEO4J_VALUES_FILE="${NEO4J_VALUES_FILE:-deploy/helm/neo4j/values-azure.yaml}"
NEO4J_VALUES_ARGS=(--values deploy/helm/neo4j/values.yaml)
if [ -f "$NEO4J_VALUES_FILE" ]; then
    NEO4J_VALUES_ARGS+=(--values "$NEO4J_VALUES_FILE")
fi
kubectl create secret generic neo4j-bootstrap-auth \
    --from-literal=NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
    --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install neo4j neo4j/neo4j \
    --namespace default \
    "${NEO4J_VALUES_ARGS[@]}" \
    --set neo4j.passwordFromSecret=neo4j-bootstrap-auth \
    --wait --timeout 180s

# -----------------------------------------------------------
# 6. Deploy NGINX Ingress Controller
# -----------------------------------------------------------
echo ""
echo "Step 6: Deploying NGINX Ingress..."
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>/dev/null || true
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
    --namespace ingress-nginx \
    --create-namespace \
    --set controller.service.type=LoadBalancer \
    --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path"=/healthz \
    --wait --timeout 120s || echo "  Ingress controller install (may already exist)"

# Apply ingress routing rules
kubectl apply -f deploy/ingress/nginx.yaml

# -----------------------------------------------------------
# 7. Deploy Backend API
# -----------------------------------------------------------
echo ""
echo "Step 7: Deploying Backend API..."
ACR_URI="${ACR_NAME}.azurecr.io"
TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "v0.1.0")

# Apply staging overrides if HELM_VALUES_FILE is set or ENV=staging
HELM_VALUES_FILE="${HELM_VALUES_FILE:-}"
HELM_EXTRA_VALUES=""
if [ -n "$HELM_VALUES_FILE" ]; then
    HELM_EXTRA_VALUES="-f $HELM_VALUES_FILE"
elif [ "${ENV:-}" = "staging" ]; then
    HELM_EXTRA_VALUES="-f deploy/helm/api/values-staging.yaml"
fi

helm upgrade --install api deploy/helm/api \
    -f deploy/helm/api/values-azure.yaml \
    $HELM_EXTRA_VALUES \
    --set image.repository="${ACR_URI}/rag-backend-api" \
    --set image.tag="${TAG}" \
    --set serviceAccount.annotations."azure\.workload\.identity/client-id"="${API_IDENTITY_CLIENT_ID}" \
    --wait --timeout 120s

# -----------------------------------------------------------
# Summary
# -----------------------------------------------------------
echo ""
echo "========================================"
echo "  AKS Cluster Bootstrap Complete!"
echo "========================================"
echo ""
echo "  Pods:"
kubectl get pods --no-headers 2>/dev/null | while read line; do echo "    $line"; done
echo ""
echo "  Services:"
kubectl get svc --no-headers 2>/dev/null | while read line; do echo "    $line"; done
echo ""
echo "  Ingress:"
kubectl get ingress --no-headers 2>/dev/null | while read line; do echo "    $line"; done
echo ""
echo "  Next: Run 'python3 scripts/init_cloud.py' to initialize databases."
echo "  Monitor: kubectl get pods -w"
echo ""
