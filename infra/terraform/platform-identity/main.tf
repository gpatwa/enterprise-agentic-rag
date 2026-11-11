# Platform identity: the one place that creates the CI identities for the pilot infrastructure.
#
# For each product repository it creates two Entra app registrations that GitHub Actions signs in as with OIDC (no stored
# secret anywhere):
#   plan  - read-only. Used on pull requests and for drift checks. Can read the resource group, the Terraform state and
#           (Analytics) the Key Vault secrets the plan needs.
#   apply - used only from protected GitHub environments on main. Owner of ITS resource group only, writer of its state
#           blob, and Entra "Application.ReadWrite.OwnedBy" (it can change only the app registrations it owns).
# It also writes the non-secret IDs the workflows need as repository variables and creates the protected environments.
#
# Everything here is scoped to the two pilot resource groups and the state storage account. Nothing touches the
# subscription's other resource groups.
#
# This stack is the root of trust, so it is applied by a person (or by Claude Code in the owner's session) with the owner's
# own `az` and `gh` logins, never from CI. Run it with scripts/platform_identity.sh. Adding a repository is one entry in
# `local.targets`.
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.117"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.53"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.4"
    }
  }
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
  storage_use_azuread = true
}

provider "azuread" {}

# Auth comes from the GITHUB_TOKEN environment variable (scripts/platform_identity.sh fills it from `gh auth token`).
provider "github" {
  owner = var.github_owner
}

variable "github_owner" {
  type    = string
  default = "gpatwa"
}

variable "state_resource_group" {
  type    = string
  default = "terraform-state-rg"
}

variable "state_storage_account" {
  type    = string
  default = "ragterraformstategp"
}

variable "state_container" {
  type    = string
  default = "tfstate"
}

data "azurerm_client_config" "current" {}
data "azuread_client_config" "current" {}

locals {
  targets = {
    discovery = {
      repository     = "agentic-search-discovery"
      resource_group = "discovery-pilot-rg"
      state_key      = "discovery-pilot/terraform.tfstate"
      key_vault      = null
      # Existing Entra apps the apply identity must own to be able to change them (created before this stack existed,
      # owned by a person). Apps the stack creates later are owned by the apply identity from the start.
      owned_apps = ["discovery-pilot-web", "discovery-pilot-github-vm-operator"]
    }
    analytics = {
      repository     = "agentic-data-analytics"
      resource_group = "compass-pilot-rg"
      state_key      = "analytics-pilot/terraform.tfstate"
      key_vault      = "compass-pilot-kv"
      owned_apps     = ["compass-pilot-analytics-api"]
    }
  }

  environments = {
    auto        = "infra-apply"
    destructive = "infra-apply-destructive"
  }

  graph_roles = {
    plan  = ["Directory.Read.All"]
    apply = ["Directory.Read.All", "Application.ReadWrite.OwnedBy"]
  }

  state_container_scope = "${data.azurerm_storage_account.state.id}/blobServices/default/containers/${var.state_container}"
}

data "azurerm_subscription" "current" {}

data "azurerm_storage_account" "state" {
  name                = var.state_storage_account
  resource_group_name = var.state_resource_group
}

data "azurerm_resource_group" "target" {
  for_each = local.targets
  name     = each.value.resource_group
}

data "azurerm_key_vault" "target" {
  for_each            = { for k, v in local.targets : k => v if v.key_vault != null }
  name                = each.value.key_vault
  resource_group_name = local.targets[each.key].resource_group
}
