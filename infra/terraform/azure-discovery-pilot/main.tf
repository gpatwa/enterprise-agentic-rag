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
  }
  # Partial backend: terraform init -backend-config=backend.hcl (see README.md)
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
}

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
