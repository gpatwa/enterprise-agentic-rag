# Analytics pilot on Azure Container Apps: the lowest-cost footprint for one governed API replica.
# Separate state from the AKS-based platform in ../azure. Nothing here is applied by automation; see README.md.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.117"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.53"
    }
  }
  # Partial backend: terraform init -backend-config=backend.hcl (see README.md)
  backend "azurerm" {}
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
  }
}

provider "azuread" {}

data "azurerm_client_config" "current" {}

locals {
  name = "${var.prefix}-${var.environment}"
  tags = {
    Product     = "compass-analytics"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
  acr_login_server = var.existing_acr_login_server != "" ? var.existing_acr_login_server : azurerm_container_registry.acr[0].login_server
  pg_host          = azurerm_postgresql_flexible_server.pg.fqdn
  control_db_url   = "postgresql://${var.postgres_admin_user}:${urlencode(var.postgres_admin_password)}@${local.pg_host}:5432/analytics_control?sslmode=require"
  warehouse_db_url = "postgresql://analytics_readonly:${urlencode(var.postgres_readonly_password)}@${local.pg_host}:5432/analytics_warehouse?sslmode=require"
  openai_endpoint  = var.create_openai ? azurerm_cognitive_account.openai[0].endpoint : var.azure_openai_endpoint
  has_openai_key   = var.create_openai || var.azure_openai_api_key != ""
  openai_key       = var.create_openai ? azurerm_cognitive_account.openai[0].primary_access_key : var.azure_openai_api_key
  entra_audience   = var.create_entra_app ? "api://${var.prefix}-${var.environment}-analytics" : var.entra_audience
}

resource "azurerm_resource_group" "rg" {
  name     = "${local.name}-rg"
  location = var.location
  tags     = local.tags
}
