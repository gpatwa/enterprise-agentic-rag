# infra/terraform/azure/monitoring.tf
# Azure Log Analytics Workspace — centralised log storage for AKS and app telemetry.
#
# Previously created manually (auto-provisioned by Azure when AKS was first set up).
# Brought under Terraform management to enable cost control and consistent teardown.
#
# To import the existing workspace:
#   Run: ./scripts/terraform_import_azure.sh
#
# Cost levers:
#   - retention_in_days: 30 is the minimum (free tier). Each extra day costs ~$0.10/GB.
#   - daily_quota_gb:    Caps ingestion to prevent runaway log costs. -1 = unlimited.

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.cluster_name}-logs"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018" # Pay-per-GB (only billing model available since 2018)

  # Dev: 30 days minimum — change to 60-90 for staging/prod
  retention_in_days = var.log_retention_days

  # Safety cap: stop ingesting after this many GB/day (avoids surprise bills).
  # -1 = no cap. For dev, 1 GB/day is generous.
  daily_quota_gb = var.log_daily_quota_gb

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# Wire AKS diagnostic logs into the workspace.
# This replaces the auto-provisioned OMS agent connection so teardown works cleanly.
resource "azurerm_monitor_diagnostic_setting" "aks" {
  name                       = "aks-diagnostics"
  target_resource_id         = azurerm_kubernetes_cluster.aks.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  # Control plane logs — useful for debugging scheduler/auth issues
  enabled_log {
    category = "kube-apiserver"
  }
  enabled_log {
    category = "kube-controller-manager"
  }
  enabled_log {
    category = "kube-scheduler"
  }
  # Node-level metrics
  metric {
    category = "AllMetrics"
    enabled  = true
  }
}
