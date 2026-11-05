# Discovery pilot on Azure Container Apps: the smallest footprint that serves the fictional-catalog demo.
# No database, search cluster or model: the API runs on fake providers over a seeded catalog.
# Separate state and resource group from every other stack. Nothing here is applied by automation; see README.md.

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
    # Container Apps built-in authentication has no azurerm resource in 3.x.
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
  # Partial backend: terraform init -backend-config=backend.hcl (see README.md)
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
  # The data storage account has shared keys disabled, so the provider must use Entra for its data-plane reads.
  storage_use_azuread = true
}

provider "azuread" {}

provider "azapi" {}

data "azuread_client_config" "current" {}

locals {
  name = "${var.prefix}-${var.environment}"
  tags = {
    Product     = "discovery"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "azurerm_resource_group" "rg" {
  name     = "${local.name}-rg"
  location = var.location
  tags     = local.tags
}
