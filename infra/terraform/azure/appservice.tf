# infra/terraform/azure/appservice.tf
# Azure App Service — static frontend / lightweight web host.
#
# NOTE: This resource has NO references in the application code and appears
# to have been created manually as an experiment. It is brought under
# Terraform management so it can be destroyed cleanly and stopped during
# cost-saving pauses.
#
# If this resource is no longer needed, set var.appservice_enabled = false
# and run `terraform apply` to destroy it, saving ~$0.99/day.
#
# To import the existing App Service:
#   Run: ./scripts/terraform_import_azure.sh

resource "azurerm_service_plan" "main" {
  count               = var.appservice_enabled ? 1 : 0
  name                = "${var.cluster_name}-asp"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  # Dev: Free F1 (0 cost) or Basic B1 (~$13/mo).
  # The existing resource bills ~$0.99/day → likely Basic B1 or B2.
  os_type  = "Linux"
  sku_name = var.appservice_sku # Default: "B1"

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

resource "azurerm_linux_web_app" "main" {
  count               = var.appservice_enabled ? 1 : 0
  name                = "${var.cluster_name}-app"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main[0].id

  site_config {
    always_on = var.appservice_sku == "F1" ? false : true # Free tier doesn't support always_on
  }

  app_settings = {
    "CLOUD_PROVIDER" = "azure"
    "ENVIRONMENT"    = var.environment
  }

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}
