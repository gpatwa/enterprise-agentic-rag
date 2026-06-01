#!/bin/bash
# scripts/resume_azure.sh
# Resume Azure managed services after a cost-saving pause.
# Counterpart to scripts/pause_azure.sh.
#
# What this does:
#   1. Starts PostgreSQL Flexible Server  (if stopped)
#   2. Redis is recreated by Terraform on next `make infra-azure` / `make deploy-azure`
#   3. Runs `make bootstrap-azure` instructions reminder
#
# Usage:
#   ./scripts/resume_azure.sh
#   make resume-azure

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rag-platform-rg}"
POSTGRES_NAME="${POSTGRES_NAME:-ragplatform-pgdb-central}"

# ─── helpers ────────────────────────────────────────────────────────────────

check_az() {
    if ! command -v az &>/dev/null; then
        echo "ERROR: Azure CLI (az) not found. Install from https://aka.ms/install-azure-cli"
        exit 1
    fi
    if ! az account show &>/dev/null 2>&1; then
        echo "ERROR: Not logged in to Azure. Run: az login"
        exit 1
    fi
}

section() {
    echo ""
    echo "──────────────────────────────────────────────"
    echo "  $1"
    echo "──────────────────────────────────────────────"
}

# ─── preflight ───────────────────────────────────────────────────────────────

echo "=============================================="
echo "  Azure Resume"
echo "  Resource Group: $RESOURCE_GROUP"
echo "=============================================="

check_az

# ─── 1. Start PostgreSQL ─────────────────────────────────────────────────────

section "Step 1: Start PostgreSQL Flexible Server"

PG_STATE=$(az postgres flexible-server show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$POSTGRES_NAME" \
    --query "state" -o tsv 2>/dev/null || echo "NotFound")

if [ "$PG_STATE" = "NotFound" ]; then
    echo "  SKIP: PostgreSQL server '$POSTGRES_NAME' not found."
    echo "        It may have been deleted. Run 'make infra-azure' to recreate."
elif [ "$PG_STATE" = "Ready" ]; then
    echo "  SKIP: PostgreSQL is already running."
else
    echo "  Current state: $PG_STATE"
    echo "  Starting PostgreSQL (takes ~1-2 min)..."
    az postgres flexible-server start \
        --resource-group "$RESOURCE_GROUP" \
        --name "$POSTGRES_NAME"

    # Wait for Ready state
    echo "  Waiting for PostgreSQL to be ready..."
    for i in $(seq 1 20); do
        STATE=$(az postgres flexible-server show \
            --resource-group "$RESOURCE_GROUP" \
            --name "$POSTGRES_NAME" \
            --query "state" -o tsv 2>/dev/null || echo "Unknown")
        if [ "$STATE" = "Ready" ]; then
            echo "  DONE: PostgreSQL is ready."
            break
        fi
        echo "    State: $STATE — waiting 15s ($i/20)..."
        sleep 15
    done
fi

# ─── 2. Redis reminder ───────────────────────────────────────────────────────

section "Step 2: Redis Cache"

REDIS_EXISTS=$(az redis show \
    --resource-group "$RESOURCE_GROUP" \
    --name "rag-platform-aks-redis" \
    --query "name" -o tsv 2>/dev/null || echo "")

if [ -n "$REDIS_EXISTS" ]; then
    echo "  Redis is already running."
else
    echo "  Redis was deleted during pause."
    echo "  It will be recreated automatically when you run:"
    echo "    make infra-azure   (Terraform recreates it)"
    echo "    make deploy-azure  (full redeploy)"
fi

# ─── 3. Start App Service ────────────────────────────────────────────────────

section "Step 3: Start App Service"

WEBAPPS=$(az webapp list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[].name" -o tsv 2>/dev/null || echo "")

if [ -z "$WEBAPPS" ]; then
    echo "  SKIP: No App Service apps found."
    echo "        If the App Service Plan was deleted, recreate via Azure Portal"
    echo "        or add it to infra/terraform/azure/ and run 'make infra-azure'."
else
    echo "$WEBAPPS" | while read -r app; do
        STATE=$(az webapp show \
            --resource-group "$RESOURCE_GROUP" \
            --name "$app" \
            --query "state" -o tsv 2>/dev/null || echo "Unknown")
        if [ "$STATE" = "Running" ]; then
            echo "  SKIP: App '$app' is already running."
        else
            echo "  Starting app '$app'..."
            az webapp start \
                --resource-group "$RESOURCE_GROUP" \
                --name "$app"
            echo "  DONE: App '$app' started."
        fi
    done
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "=============================================="
echo "  Resume Complete!"
echo ""
echo "  Next steps to fully restore the cluster:"
echo ""
echo "  1. Recreate Redis + any destroyed infra:"
echo "       make infra-azure"
echo ""
echo "  2. Bootstrap the AKS cluster:"
echo "       make bootstrap-azure"
echo ""
echo "  3. Verify everything is healthy:"
echo "       make verify"
echo "=============================================="
