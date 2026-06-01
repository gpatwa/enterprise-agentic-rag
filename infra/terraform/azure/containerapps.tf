# infra/terraform/azure/containerapps.tf
# Azure Container Apps — serverless container runtime.
#
# NOTE: This resource has NO references in the application code. The main
# workloads run on AKS. This environment appears to have been created manually
# as an early prototype or experiment.
#
# It is brought under Terraform management so it can be cleanly destroyed.
# To remove it entirely, set var.containerapps_enabled = false and apply.
# Saves ~$2.29/day.
#
# To import the existing environment:
#   Run: ./scripts/terraform_import_azure.sh

# Container Apps requires a Log Analytics workspace for its own log stream.
# We reuse the central workspace defined in monitoring.tf.
resource "azurerm_container_app_environment" "main" {
  count                      = var.containerapps_enabled ? 1 : 0
  name                       = "${var.cluster_name}-cae"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# Placeholder app to keep the environment non-empty.
# Replace with a real workload definition if Container Apps are adopted.
resource "azurerm_container_app" "placeholder" {
  count                        = var.containerapps_enabled ? 1 : 0
  name                         = "${var.cluster_name}-placeholder"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main[0].id
  revision_mode                = "Single"

  template {
    container {
      name   = "placeholder"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 0.25
      memory = "0.5Gi"
    }
    # Scale to zero when idle — eliminates compute cost
    min_replicas = 0
    max_replicas = 1
  }

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}
