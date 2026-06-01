#!/bin/bash
# scripts/pause_azure.sh
# Pause non-destructive Azure resources to stop billing while the AKS
# cluster is offline.  Safe to run at any time — no data is lost.
#
# What this does:
#   1. Stops PostgreSQL Flexible Server  (billing pauses; data preserved)
#   2. Deletes Redis Cache               (no persistent data; rebuilt on redeploy)
#   3. Releases any orphaned public IPs  (left behind by ingress-nginx LB)
#   4. Prunes old ACR image tags         (keeps last 2; reduces storage billing)
#   5. Stops App Service + Plan          (stops compute billing; app preserved)
#   6. Reduces Log Analytics retention   (cuts ingestion + storage cost)
#
# Estimated savings: ~$19-20/day
#
# Usage:
#   ./scripts/pause_azure.sh            # Interactive (asks before each step)
#   ./scripts/pause_azure.sh --force    # Skip confirmations (CI-safe)
#
# To bring everything back:
#   ./scripts/resume_azure.sh           (or: make resume-azure)

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rag-platform-rg}"
POSTGRES_NAME="${POSTGRES_NAME:-ragplatform-pgdb-central}"
REDIS_NAME="${REDIS_NAME:-rag-platform-aks-redis}"
ACR_NAME="${ACR_NAME:-ragplatformacr}"
ACR_REPO="${ACR_REPO:-rag-backend-api}"
ACR_KEEP_TAGS="${ACR_KEEP_TAGS:-2}"    # Number of most-recent tags to keep
ACR_PURGE_AGO="${ACR_PURGE_AGO:-7d}"  # Purge tags older than this

FORCE=false
[ "${1:-}" = "--force" ] && FORCE=true

SAVINGS=0

# ─── helpers ────────────────────────────────────────────────────────────────

confirm() {
    local prompt="$1"
    if [ "$FORCE" = true ]; then
        echo "  [--force] $prompt — proceeding"
        return 0
    fi
    read -rp "  $prompt [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

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
echo "  Azure Cost Pause"
echo "  Resource Group: $RESOURCE_GROUP"
echo "=============================================="

check_az

# ─── 1. Stop PostgreSQL ──────────────────────────────────────────────────────

section "Step 1: Stop PostgreSQL Flexible Server (~\$5.20/day saved)"

PG_STATE=$(az postgres flexible-server show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$POSTGRES_NAME" \
    --query "state" -o tsv 2>/dev/null || echo "NotFound")

if [ "$PG_STATE" = "NotFound" ]; then
    echo "  SKIP: PostgreSQL server '$POSTGRES_NAME' not found."
elif [ "$PG_STATE" = "Stopped" ]; then
    echo "  SKIP: PostgreSQL is already stopped."
else
    echo "  Current state: $PG_STATE"
    echo "  NOTE: Data is preserved. Azure auto-restarts after 7 days."
    if confirm "Stop PostgreSQL '$POSTGRES_NAME'?"; then
        az postgres flexible-server stop \
            --resource-group "$RESOURCE_GROUP" \
            --name "$POSTGRES_NAME"
        echo "  DONE: PostgreSQL stopped."
        SAVINGS=$((SAVINGS + 5))
    else
        echo "  SKIPPED."
    fi
fi

# ─── 2. Delete Redis Cache ───────────────────────────────────────────────────

section "Step 2: Delete Redis Cache (~\$6.69/day saved)"

REDIS_EXISTS=$(az redis show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$REDIS_NAME" \
    --query "name" -o tsv 2>/dev/null || echo "")

if [ -z "$REDIS_EXISTS" ]; then
    echo "  SKIP: Redis cache '$REDIS_NAME' not found (already deleted?)."
else
    echo "  NOTE: Redis holds only ephemeral cache data (sessions, embeddings)."
    echo "        It will be recreated automatically on next deploy."
    if confirm "Delete Redis '$REDIS_NAME'? (no data loss for dev)"; then
        az redis delete \
            --resource-group "$RESOURCE_GROUP" \
            --name "$REDIS_NAME" \
            --yes
        echo "  DONE: Redis deleted."
        SAVINGS=$((SAVINGS + 6))
    else
        echo "  SKIPPED."
    fi
fi

# ─── 3. Release orphaned public IPs (Load Balancer) ─────────────────────────

section "Step 3: Release orphaned public IPs (~\$3.80/day saved)"

echo "  Scanning for unattached public IPs in '$RESOURCE_GROUP'..."

# List public IPs with no associated resource (orphaned)
ORPHANED_IPS=$(az network public-ip list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[?ipConfiguration==null].name" \
    -o tsv 2>/dev/null || echo "")

if [ -z "$ORPHANED_IPS" ]; then
    echo "  SKIP: No orphaned public IPs found."
else
    echo "  Found orphaned IPs:"
    echo "$ORPHANED_IPS" | while read -r ip_name; do
        echo "    - $ip_name"
    done
    if confirm "Delete all orphaned public IPs?"; then
        echo "$ORPHANED_IPS" | while read -r ip_name; do
            az network public-ip delete \
                --resource-group "$RESOURCE_GROUP" \
                --name "$ip_name"
            echo "  DONE: Deleted public IP '$ip_name'."
        done
        SAVINGS=$((SAVINGS + 3))
    else
        echo "  SKIPPED."
    fi
fi

# Also check for orphaned load balancers (created by ingress-nginx)
echo ""
echo "  Scanning for orphaned Load Balancers..."

ORPHANED_LBS=$(az network lb list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[?contains(name, 'kubernetes') || contains(name, 'nginx')].name" \
    -o tsv 2>/dev/null || echo "")

if [ -z "$ORPHANED_LBS" ]; then
    echo "  SKIP: No orphaned Kubernetes/Nginx Load Balancers found."
else
    echo "  Found orphaned Load Balancers:"
    echo "$ORPHANED_LBS" | while read -r lb_name; do
        echo "    - $lb_name"
    done
    if confirm "Delete orphaned Load Balancers?"; then
        echo "$ORPHANED_LBS" | while read -r lb_name; do
            az network lb delete \
                --resource-group "$RESOURCE_GROUP" \
                --name "$lb_name"
            echo "  DONE: Deleted Load Balancer '$lb_name'."
        done
    else
        echo "  SKIPPED."
    fi
fi

# ─── 4. Prune ACR images ─────────────────────────────────────────────────────

section "Step 4: Prune old ACR images (~\$2-3/day saved)"

ACR_EXISTS=$(az acr show \
    --name "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "name" -o tsv 2>/dev/null || echo "")

if [ -z "$ACR_EXISTS" ]; then
    echo "  SKIP: ACR '$ACR_NAME' not found."
else
    echo "  Purging '$ACR_REPO' tags older than $ACR_PURGE_AGO, keeping last $ACR_KEEP_TAGS."
    if confirm "Purge old ACR images?"; then
        az acr run \
            --registry "$ACR_NAME" \
            --cmd "acr purge \
                --filter '${ACR_REPO}:.*' \
                --ago ${ACR_PURGE_AGO} \
                --keep ${ACR_KEEP_TAGS} \
                --untagged" \
            /dev/null
        echo "  DONE: ACR images pruned."
        SAVINGS=$((SAVINGS + 2))
    else
        echo "  SKIPPED."
    fi
fi

# ─── 5. Stop App Service + App Service Plan ──────────────────────────────────

section "Step 5: Stop App Service (~\$0.99/day saved)"

# Discover all web apps in the resource group
WEBAPPS=$(az webapp list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[].name" -o tsv 2>/dev/null || echo "")

if [ -z "$WEBAPPS" ]; then
    echo "  SKIP: No App Service apps found in '$RESOURCE_GROUP'."
else
    echo "  Found App Service apps:"
    echo "$WEBAPPS" | while read -r app; do
        STATE=$(az webapp show \
            --resource-group "$RESOURCE_GROUP" \
            --name "$app" \
            --query "state" -o tsv 2>/dev/null || echo "Unknown")
        echo "    - $app  (state: $STATE)"
    done
    echo "  NOTE: Stopping pauses compute billing. App config and data are preserved."
    if confirm "Stop all App Service apps?"; then
        echo "$WEBAPPS" | while read -r app; do
            az webapp stop \
                --resource-group "$RESOURCE_GROUP" \
                --name "$app"
            echo "  DONE: Stopped app '$app'."
        done
        SAVINGS=$((SAVINGS + 1))
    else
        echo "  SKIPPED."
    fi
fi

# Also stop the App Service Plans (the underlying compute)
APP_PLANS=$(az appservice plan list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[?sku.tier!='Free' && sku.tier!='Shared'].name" \
    -o tsv 2>/dev/null || echo "")

if [ -n "$APP_PLANS" ]; then
    echo ""
    echo "  Found paid App Service Plans (these bill even when apps are stopped):"
    echo "$APP_PLANS" | while read -r plan; do
        SKU=$(az appservice plan show \
            --resource-group "$RESOURCE_GROUP" \
            --name "$plan" \
            --query "sku.name" -o tsv 2>/dev/null || echo "Unknown")
        echo "    - $plan  (SKU: $SKU)"
    done
    echo "  NOTE: Deleting the plan stops all compute billing. Apps can be reassigned on resume."
    if confirm "Delete paid App Service Plans?"; then
        echo "$APP_PLANS" | while read -r plan; do
            az appservice plan delete \
                --resource-group "$RESOURCE_GROUP" \
                --name "$plan" \
                --yes
            echo "  DONE: Deleted App Service Plan '$plan'."
        done
    else
        echo "  SKIPPED (plan continues billing even with app stopped)."
    fi
fi

# ─── 6. Reduce Log Analytics retention ───────────────────────────────────────

section "Step 6: Reduce Log Analytics retention (~\$1/day saved)"

# Discover Log Analytics workspaces in the resource group
WORKSPACES=$(az monitor log-analytics workspace list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[].name" -o tsv 2>/dev/null || echo "")

if [ -z "$WORKSPACES" ]; then
    echo "  SKIP: No Log Analytics workspaces found in '$RESOURCE_GROUP'."
else
    echo "  Found workspaces:"
    echo "$WORKSPACES" | while read -r ws; do
        RETENTION=$(az monitor log-analytics workspace show \
            --resource-group "$RESOURCE_GROUP" \
            --workspace-name "$ws" \
            --query "retentionInDays" -o tsv 2>/dev/null || echo "?")
        echo "    - $ws  (retention: ${RETENTION} days)"
    done
    echo "  NOTE: Reducing retention to 30 days (minimum) cuts storage cost."
    echo "        No live data is lost — only old logs beyond 30 days are trimmed."
    if confirm "Set all workspaces to 30-day retention?"; then
        echo "$WORKSPACES" | while read -r ws; do
            az monitor log-analytics workspace update \
                --resource-group "$RESOURCE_GROUP" \
                --workspace-name "$ws" \
                --retention-time 30
            echo "  DONE: Workspace '$ws' set to 30-day retention."
        done
        SAVINGS=$((SAVINGS + 1))
    else
        echo "  SKIPPED."
    fi
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "=============================================="
echo "  Pause Complete!"
echo "  Estimated savings: ~\$$SAVINGS/day"
echo ""
echo "  Remaining baseline costs:"
echo "    - Storage account (blobs/backups)   ~\$0.10/day"
echo "    - Key Vault (API calls)             ~\$0.00/day"
echo "    - Azure DNS zone                    ~\$0.10/day"
echo "    - VNet (free unless NAT Gateway)    ~\$0.00/day"
echo "    - Log Analytics (30-day min)        ~\$0.50/day"
echo "    - PostgreSQL storage (if stopped)   ~\$0.12/day"
echo "    ─────────────────────────────────────────"
echo "    Total remaining:                    ~\$0.80-1.00/day"
echo ""
echo "  To resume when ready:"
echo "    make resume-azure"
echo "    (or: ./scripts/resume_azure.sh)"
echo ""
echo "  To fully destroy everything:"
echo "    make destroy-azure"
echo "=============================================="
