#!/usr/bin/env bash
# scripts/bootstrap_alpha_secret.sh
#
# Minimal alpha-grade bootstrap: creates ONLY the `app-env-secret`
# Kubernetes Secret that the API deployment reads via envFrom. No
# KubeRay / Qdrant / Neo4j installs (those are deferred until the
# alpha needs full agent capability — for the UI demo we don't need
# vector/graph search to actually return results).
#
# Run AFTER `terraform apply` finishes provisioning the AKS cluster +
# Postgres + Redis. Uses Terraform outputs to wire up DATABASE_URL,
# REDIS_URL, and storage / Key Vault references.
#
# Idempotent: re-running updates the secret in place.
#
# Usage
# -----
#     # From repo root:
#     ./scripts/bootstrap_alpha_secret.sh
#
# Prerequisites
# -------------
#     - kubectl configured for the target AKS (`az aks get-credentials`)
#     - Terraform state reachable from infra/terraform/azure/
#     - DB_PASSWORD in env (or it's read from terraform.tfvars)
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-rag-platform-aks}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rag-platform-rg}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "─── Alpha secret bootstrap ─────────────────────────────"
echo "  cluster: $CLUSTER_NAME / $RESOURCE_GROUP"

# 1. kubeconfig
echo ""
echo "1) Pulling AKS credentials"
az aks get-credentials \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CLUSTER_NAME" \
  --overwrite-existing > /dev/null

# 2. Read terraform outputs
echo ""
echo "2) Reading terraform outputs"
cd "$PROJECT_DIR/infra/terraform/azure"
POSTGRES_FQDN=$(terraform output -raw postgres_fqdn)
REDIS_HOST=$(terraform output -raw redis_hostname)
REDIS_PORT=$(terraform output -raw redis_ssl_port)
REDIS_KEY=$(terraform output -raw redis_primary_key)
STORAGE_ACCOUNT=$(terraform output -raw storage_account_name)
KEY_VAULT_URL=$(terraform output -raw key_vault_url)
echo "   postgres: $POSTGRES_FQDN"
echo "   redis:    $REDIS_HOST"
echo "   kv:       $KEY_VAULT_URL"
cd "$PROJECT_DIR"

# 3. DB password — prefer env, fall back to tfvars (gitignored, safe-ish)
if [ -z "${DB_PASSWORD:-}" ]; then
  DB_PASSWORD=$(grep '^db_password' "$PROJECT_DIR/infra/terraform/azure/terraform.tfvars" \
    | sed 's/.*= *"\(.*\)"$/\1/')
fi
if [ -z "$DB_PASSWORD" ]; then
  echo "ERROR: DB_PASSWORD not in env and not readable from terraform.tfvars" >&2
  exit 1
fi

JWT_SECRET_KEY=$(grep '^jwt_secret_key' "$PROJECT_DIR/infra/terraform/azure/terraform.tfvars" \
  | sed 's/.*= *"\(.*\)"$/\1/')
NEO4J_PASSWORD=$(grep '^neo4j_password' "$PROJECT_DIR/infra/terraform/azure/terraform.tfvars" \
  | sed 's/.*= *"\(.*\)"$/\1/')

DATABASE_URL="postgresql+asyncpg://ragadmin:${DB_PASSWORD}@${POSTGRES_FQDN}:5432/ragdb"
REDIS_URL="rediss://:${REDIS_KEY}@${REDIS_HOST}:${REDIS_PORT}/0"

# 4. Apply the secret (kubectl create --dry-run=client | apply for idempotency)
echo ""
echo "3) Creating/updating app-env-secret"
SECRET_ARGS=(
  --from-literal=DATABASE_URL="$DATABASE_URL"
  --from-literal=REDIS_URL="$REDIS_URL"
  --from-literal=JWT_SECRET_KEY="$JWT_SECRET_KEY"
  --from-literal=NEO4J_PASSWORD="$NEO4J_PASSWORD"
  --from-literal=AZURE_STORAGE_ACCOUNT_NAME="$STORAGE_ACCOUNT"
  --from-literal=AZURE_KEY_VAULT_URL="$KEY_VAULT_URL"
  --from-literal=CLOUD_PROVIDER="azure"
  --from-literal=STORAGE_PROVIDER="azure_blob"
  --from-literal=SECRETS_PROVIDER="azure_kv"
)

# Optional: feedback widget Slack webhook (B.1)
if [ -n "${FEEDBACK_SLACK_WEBHOOK_URL:-}" ]; then
  SECRET_ARGS+=(--from-literal=FEEDBACK_SLACK_WEBHOOK_URL="$FEEDBACK_SLACK_WEBHOOK_URL")
  echo "   FEEDBACK_SLACK_WEBHOOK_URL: set"
fi

# Optional: Sentry (B.3)
if [ -n "${SENTRY_DSN:-}" ]; then
  SECRET_ARGS+=(--from-literal=SENTRY_DSN="$SENTRY_DSN")
  echo "   SENTRY_DSN: set"
fi

# Optional: MCP encryption key
if [ -n "${MCP_ENCRYPTION_KEY:-}" ]; then
  SECRET_ARGS+=(--from-literal=MCP_ENCRYPTION_KEY="$MCP_ENCRYPTION_KEY")
  echo "   MCP_ENCRYPTION_KEY: set"
fi

kubectl create secret generic app-env-secret \
  "${SECRET_ARGS[@]}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "✓ app-env-secret applied. Trigger deploy-staging workflow next."
