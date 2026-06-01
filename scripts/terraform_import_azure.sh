#!/bin/bash
# scripts/terraform_import_azure.sh
# Import manually-created Azure resources into Terraform state.
#
# Run this ONCE before the first `terraform apply` to avoid Terraform
# trying to create duplicates of resources that already exist.
#
# Resources imported:
#   - Log Analytics workspace
#   - DNS zone (patwa-rag-platform.com)
#   - App Service Plan + Web App
#   - Container Apps environment
#   - Service Bus namespace
#
# Usage:
#   cd infra/terraform/azure
#   ../../../scripts/terraform_import_azure.sh
#
# Prerequisites:
#   - az login
#   - terraform init

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rag-platform-rg}"
CLUSTER_NAME="${CLUSTER_NAME:-rag-platform-aks}"
DNS_ZONE="${DNS_ZONE:-patwa-rag-platform.com}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TF_DIR="$(dirname "$SCRIPT_DIR")/infra/terraform/azure"

echo "=============================================="
echo "  Terraform Import — Azure Manual Resources"
echo "  Resource Group: $RESOURCE_GROUP"
echo "=============================================="

check_az() {
    if ! command -v az &>/dev/null; then
        echo "ERROR: Azure CLI not found."
        exit 1
    fi
    if ! az account show &>/dev/null 2>&1; then
        echo "ERROR: Not logged in. Run: az login"
        exit 1
    fi
}

check_tf() {
    if ! command -v terraform &>/dev/null; then
        echo "ERROR: terraform not found."
        exit 1
    fi
}

section() {
    echo ""
    echo "──────────────────────────────────────────────"
    echo "  $1"
    echo "──────────────────────────────────────────────"
}

import_if_exists() {
    local label="$1"
    local tf_address="$2"
    local az_id="$3"

    if [ -z "$az_id" ]; then
        echo "  SKIP ($label): resource not found in Azure."
        return
    fi

    # Check if already in state
    if terraform state show "$tf_address" &>/dev/null 2>&1; then
        echo "  SKIP ($label): already in Terraform state."
        return
    fi

    echo "  Importing $label..."
    terraform import "$tf_address" "$az_id"
    echo "  DONE: $label imported."
}

check_az
check_tf

cd "$TF_DIR"
echo ""
echo "Working directory: $(pwd)"
echo ""
terraform init -upgrade 2>/dev/null | tail -3

# ─── 1. Log Analytics Workspace ──────────────────────────────────────────────

section "1. Log Analytics Workspace"

LOG_WS_ID=$(az monitor log-analytics workspace list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "Log Analytics Workspace" \
    "azurerm_log_analytics_workspace.main" \
    "$LOG_WS_ID"

# ─── 2. DNS Zone ─────────────────────────────────────────────────────────────

section "2. DNS Zone"

DNS_ZONE_ID=$(az network dns zone show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$DNS_ZONE" \
    --query "id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "DNS Zone ($DNS_ZONE)" \
    "azurerm_dns_zone.main" \
    "$DNS_ZONE_ID"

# Import A record if it exists
API_RECORD_ID=$(az network dns record-set a show \
    --resource-group "$RESOURCE_GROUP" \
    --zone-name "$DNS_ZONE" \
    --name "api" \
    --query "id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "DNS A record (api.$DNS_ZONE)" \
    "azurerm_dns_a_record.api[0]" \
    "$API_RECORD_ID"

# Import CNAME record if it exists
WWW_RECORD_ID=$(az network dns record-set cname show \
    --resource-group "$RESOURCE_GROUP" \
    --zone-name "$DNS_ZONE" \
    --name "www" \
    --query "id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "DNS CNAME record (www.$DNS_ZONE)" \
    "azurerm_dns_cname_record.www[0]" \
    "$WWW_RECORD_ID"

# ─── 3. App Service Plan + Web App ───────────────────────────────────────────

section "3. App Service"

APP_PLAN_ID=$(az appservice plan list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "App Service Plan" \
    "azurerm_service_plan.main[0]" \
    "$APP_PLAN_ID"

WEBAPP_ID=$(az webapp list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "App Service Web App" \
    "azurerm_linux_web_app.main[0]" \
    "$WEBAPP_ID"

# ─── 4. Container Apps Environment ───────────────────────────────────────────

section "4. Container Apps"

CAE_ID=$(az containerapp env list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "Container App Environment" \
    "azurerm_container_app_environment.main[0]" \
    "$CAE_ID"

CA_ID=$(az containerapp list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "Container App" \
    "azurerm_container_app.placeholder[0]" \
    "$CA_ID"

# ─── 5. Service Bus ──────────────────────────────────────────────────────────

section "5. Service Bus"

SB_ID=$(az servicebus namespace list \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "Service Bus Namespace" \
    "azurerm_servicebus_namespace.main[0]" \
    "$SB_ID"

SBQ_ID=$(az servicebus queue list \
    --resource-group "$RESOURCE_GROUP" \
    --namespace-name "$(az servicebus namespace list \
        --resource-group "$RESOURCE_GROUP" \
        --query "[0].name" -o tsv 2>/dev/null || echo "")" \
    --query "[?name=='document-ingestion'].id" -o tsv 2>/dev/null || echo "")

import_if_exists \
    "Service Bus Queue (document-ingestion)" \
    "azurerm_servicebus_queue.ingestion[0]" \
    "$SBQ_ID"

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "=============================================="
echo "  Import Complete!"
echo ""
echo "  Next: review the plan before applying:"
echo "    cd infra/terraform/azure"
echo "    terraform plan"
echo ""
echo "  Then apply:"
echo "    terraform apply"
echo "    (or: make infra-azure)"
echo "=============================================="
