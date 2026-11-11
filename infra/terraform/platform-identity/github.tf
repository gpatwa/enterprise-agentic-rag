# ---- GitHub: protected environments and the non-secret variables the workflows read ----------------------------------------

data "github_user" "owner" {
  username = var.github_owner
}

# Applies that only add or change run from `infra-apply` (main only, no approval). A plan that destroys or replaces anything
# runs from `infra-apply-destructive`, which waits for the owner's approval: one click, and nothing is destroyed without it.
resource "github_repository_environment" "auto" {
  for_each    = local.targets
  repository  = each.value.repository
  environment = local.environments.auto

  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_deployment_branch_policy" "auto_main" {
  for_each         = local.targets
  repository       = each.value.repository
  environment_name = github_repository_environment.auto[each.key].environment
  name             = "main"
}

resource "github_repository_environment" "destructive" {
  for_each    = local.targets
  repository  = each.value.repository
  environment = local.environments.destructive

  reviewers {
    users = [tonumber(data.github_user.owner.id)]
  }

  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_deployment_branch_policy" "destructive_main" {
  for_each         = local.targets
  repository       = each.value.repository
  environment_name = github_repository_environment.destructive[each.key].environment
  name             = "main"
}

locals {
  repo_variables = merge([
    for k, t in local.targets : {
      for name, value in merge(
        {
          AZURE_TENANT_ID         = data.azurerm_client_config.current.tenant_id
          AZURE_SUBSCRIPTION_ID   = data.azurerm_client_config.current.subscription_id
          INFRA_PLAN_CLIENT_ID    = azuread_application.plan[k].client_id
          INFRA_APPLY_CLIENT_ID   = azuread_application.apply[k].client_id
          TF_STATE_RESOURCE_GROUP = var.state_resource_group
          TF_STATE_STORAGE        = var.state_storage_account
          TF_STATE_CONTAINER      = var.state_container
          TF_STATE_KEY            = t.state_key
          PILOT_RESOURCE_GROUP    = t.resource_group
        },
        t.key_vault == null ? {} : { PILOT_KEY_VAULT = t.key_vault },
      ) : "${k}-${name}" => { target = k, name = name, value = value }
    }
  ]...)
}

resource "github_actions_variable" "this" {
  for_each      = local.repo_variables
  repository    = local.targets[each.value.target].repository
  variable_name = each.value.name
  value         = each.value.value
}
