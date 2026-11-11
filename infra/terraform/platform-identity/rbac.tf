# ---- Azure RBAC --------------------------------------------------------------------------------------------------------

# What the azurerm provider needs at subscription scope just to start (read the subscription, list resource providers, read
# resource groups), without granting Reader on everything in the subscription.
resource "azurerm_role_definition" "provider_reader" {
  name        = "terraform-provider-reader"
  scope       = data.azurerm_subscription.current.id
  description = "Lets the azurerm provider start: read the subscription, resource providers and resource groups. Nothing else."

  permissions {
    actions = [
      "Microsoft.Resources/subscriptions/read",
      "Microsoft.Resources/subscriptions/providers/read",
      "Microsoft.Resources/subscriptions/resourceGroups/read",
    ]
    not_actions = []
  }

  assignable_scopes = [data.azurerm_subscription.current.id]
}

locals {
  principals = merge(
    { for k in keys(local.targets) : "plan-${k}" => azuread_service_principal.plan[k].object_id },
    { for k in keys(local.targets) : "apply-${k}" => azuread_service_principal.apply[k].object_id },
  )
}

resource "azurerm_role_assignment" "provider_reader" {
  for_each           = local.principals
  scope              = data.azurerm_subscription.current.id
  role_definition_id = azurerm_role_definition.provider_reader.role_definition_resource_id
  principal_id       = each.value
}

# plan: read the resource group.  apply: own it (needed to create role assignments the stacks declare).
resource "azurerm_role_assignment" "plan_rg_reader" {
  for_each             = local.targets
  scope                = data.azurerm_resource_group.target[each.key].id
  role_definition_name = "Reader"
  principal_id         = azuread_service_principal.plan[each.key].object_id
}

resource "azurerm_role_assignment" "apply_rg_owner" {
  for_each             = local.targets
  scope                = data.azurerm_resource_group.target[each.key].id
  role_definition_name = "Owner"
  principal_id         = azuread_service_principal.apply[each.key].object_id
}

# Terraform state: plan reads it (and plans with -lock=false), apply reads and writes it. The data plane is reached with
# Entra auth, so no storage account key is needed anywhere.
resource "azurerm_role_assignment" "plan_state" {
  for_each             = local.targets
  scope                = local.state_container_scope
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azuread_service_principal.plan[each.key].object_id
}

resource "azurerm_role_assignment" "apply_state" {
  for_each             = local.targets
  scope                = local.state_container_scope
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azuread_service_principal.apply[each.key].object_id
}

# The person running this stack can use the same Entra auth for local Terraform runs.
resource "azurerm_role_assignment" "operator_state" {
  scope                = local.state_container_scope
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Analytics only: the secrets the plan and apply need are read from the Key Vault at run time (nothing is stored in GitHub).
resource "azurerm_role_assignment" "plan_kv" {
  for_each             = data.azurerm_key_vault.target
  scope                = each.value.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azuread_service_principal.plan[each.key].object_id
}

resource "azurerm_role_assignment" "apply_kv" {
  for_each             = data.azurerm_key_vault.target
  scope                = each.value.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = azuread_service_principal.apply[each.key].object_id
}

# The azurerm provider reads secret-bearing properties while refreshing (Cognitive Services keys, Container App and Static Web
# App secrets, registry credentials), which `Reader` does not allow. This custom role adds exactly those read actions for the
# plan identity, on its own resource group only. Plan jobs run on pull requests from this repository (forks get no OIDC token),
# so this is the owner's own code reading the owner's own pilot secrets; the Terraform logs never print them.
resource "azurerm_role_definition" "plan_refresh" {
  name        = "terraform-plan-refresh"
  scope       = data.azurerm_subscription.current.id
  description = "Read the secret-bearing properties the azurerm provider needs to refresh state. Read only."

  permissions {
    actions = [
      "Microsoft.CognitiveServices/accounts/listKeys/action",
      "Microsoft.App/containerApps/listSecrets/action",
      "Microsoft.App/jobs/listSecrets/action",
      "Microsoft.ContainerRegistry/registries/listCredentials/action",
      "Microsoft.Web/staticSites/listSecrets/action",
      "Microsoft.Web/staticSites/listAppSettings/action",
    ]
    not_actions = []
  }

  assignable_scopes = [for rg in data.azurerm_resource_group.target : rg.id]
}

resource "azurerm_role_assignment" "plan_refresh" {
  for_each           = local.targets
  scope              = data.azurerm_resource_group.target[each.key].id
  role_definition_id = azurerm_role_definition.plan_refresh.role_definition_resource_id
  principal_id       = azuread_service_principal.plan[each.key].object_id
}
