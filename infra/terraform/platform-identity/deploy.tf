# ---- The DEPLOY identity (one per repository) -------------------------------------------------------------------------------
# Used by the manual deploy workflows (build an image, push it, point the apps at it, publish a static site) from the
# `pilot-deploy` environment on main. Far narrower than the infra apply identity: it cannot touch the database, the network,
# role assignments or anything it is not named for. Replaces the stored secrets those workflows used to need.

locals {
  deploy = {
    discovery = {
      registry            = "discoverypilotacr"
      container_apps      = ["discovery-pilot-api", "discovery-pilot-web"]
      container_jobs      = []
      managed_environment = "discovery-pilot-cae"
      identities          = ["discovery-pilot-apps"]
      static_web_apps     = []
      read_key_vault      = false
    }
    analytics = {
      registry            = "compasspilotacr"
      container_apps      = ["compass-pilot-analytics-api"]
      container_jobs      = ["compass-pilot-analytics-purge"]
      managed_environment = "compass-pilot-cae"
      identities          = ["compass-pilot-analytics-api"]
      static_web_apps     = ["compass-pilot-analytics-web", "compass-pilot-landing"]
      read_key_vault      = true
    }
  }

  deploy_environment = "pilot-deploy"

  rg_id = { for k in keys(local.targets) : k => data.azurerm_resource_group.target[k].id }

  deploy_contributor_scopes = merge([
    for k, d in local.deploy : merge(
      { for n in d.container_apps : "${k}-app-${n}" => { target = k, scope = "${local.rg_id[k]}/providers/Microsoft.App/containerApps/${n}" } },
      { for n in d.container_jobs : "${k}-job-${n}" => { target = k, scope = "${local.rg_id[k]}/providers/Microsoft.App/jobs/${n}" } },
    )
  ]...)

  deploy_identity_scopes = merge([
    for k, d in local.deploy : {
      for n in d.identities : "${k}-${n}" => { target = k, scope = "${local.rg_id[k]}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${n}" }
    }
  ]...)

  deploy_swa_scopes = merge([
    for k, d in local.deploy : {
      for n in d.static_web_apps : "${k}-${n}" => { target = k, scope = "${local.rg_id[k]}/providers/Microsoft.Web/staticSites/${n}" }
    }
  ]...)

  deploy_environment_scopes = {
    for k, d in local.deploy : k => "${local.rg_id[k]}/providers/Microsoft.App/managedEnvironments/${d.managed_environment}"
  }
}

resource "azuread_application" "deploy" {
  for_each         = local.deploy
  display_name     = "${each.key}-deploy"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]
  notes            = "Code deploys for ${local.targets[each.key].repository} from the ${local.deploy_environment} environment (GitHub OIDC). Managed by infra/terraform/platform-identity."
  lifecycle { ignore_changes = [owners] }
}

resource "azuread_service_principal" "deploy" {
  for_each  = local.deploy
  client_id = azuread_application.deploy[each.key].client_id
  owners    = [data.azuread_client_config.current.object_id]
  lifecycle { ignore_changes = [owners] }
}

resource "azuread_application_federated_identity_credential" "deploy" {
  for_each       = local.deploy
  application_id = azuread_application.deploy[each.key].id
  display_name   = "github-${local.deploy_environment}"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "${local.subject_prefix[each.key]}:environment:${local.deploy_environment}"
}

# Start the azurerm-independent `az login` context.
resource "azurerm_role_assignment" "deploy_provider_reader" {
  for_each           = local.deploy
  scope              = data.azurerm_subscription.current.id
  role_definition_id = azurerm_role_definition.provider_reader.role_definition_resource_id
  principal_id       = azuread_service_principal.deploy[each.key].object_id
}

# Change exactly the apps and jobs the workflow updates (Contributor on each, nothing else in the group).
resource "azurerm_role_assignment" "deploy_contributor" {
  for_each             = local.deploy_contributor_scopes
  scope                = each.value.scope
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.deploy[each.value.target].object_id
}

# Updating an app that runs as a user-assigned identity requires permission to assign that identity.
resource "azurerm_role_assignment" "deploy_identity_operator" {
  for_each             = local.deploy_identity_scopes
  scope                = each.value.scope
  role_definition_name = "Managed Identity Operator"
  principal_id         = azuread_service_principal.deploy[each.value.target].object_id
}

resource "azurerm_role_definition" "environment_joiner" {
  name        = "pilot-environment-joiner"
  scope       = data.azurerm_subscription.current.id
  description = "Read a Container Apps environment and let an app in it be updated. Nothing else."

  permissions {
    actions = [
      "Microsoft.App/managedEnvironments/read",
      "Microsoft.App/managedEnvironments/join/action",
    ]
    not_actions = []
  }

  assignable_scopes = values(local.deploy_environment_scopes)
}

resource "azurerm_role_assignment" "deploy_environment" {
  for_each           = local.deploy
  scope              = local.deploy_environment_scopes[each.key]
  role_definition_id = azurerm_role_definition.environment_joiner.role_definition_resource_id
  principal_id       = azuread_service_principal.deploy[each.key].object_id
}

resource "azurerm_role_assignment" "deploy_acr_push" {
  for_each             = local.deploy
  scope                = "${local.rg_id[each.key]}/providers/Microsoft.ContainerRegistry/registries/${each.value.registry}"
  role_definition_name = "AcrPush"
  principal_id         = azuread_service_principal.deploy[each.key].object_id
}

# Static Web Apps: read the deployment token at run time (instead of storing it as a secret).
resource "azurerm_role_definition" "swa_token_reader" {
  name        = "pilot-static-web-app-token-reader"
  scope       = data.azurerm_subscription.current.id
  description = "Read a Static Web App and its deployment token. Nothing else."

  permissions {
    actions = [
      "Microsoft.Web/staticSites/read",
      "Microsoft.Web/staticSites/listSecrets/action",
    ]
    not_actions = []
  }

  assignable_scopes = length(local.deploy_swa_scopes) == 0 ? [data.azurerm_subscription.current.id] : [for v in values(local.deploy_swa_scopes) : v.scope]
}

resource "azurerm_role_assignment" "deploy_swa" {
  for_each           = local.deploy_swa_scopes
  scope              = each.value.scope
  role_definition_id = azurerm_role_definition.swa_token_reader.role_definition_resource_id
  principal_id       = azuread_service_principal.deploy[each.value.target].object_id
}

# Analytics: the web build reads the API key from the vault (it is embedded in the public web bundle, but it is still not
# stored in GitHub).
resource "azurerm_role_assignment" "deploy_kv" {
  for_each             = { for k, d in local.deploy : k => d if d.read_key_vault }
  scope                = data.azurerm_key_vault.target[each.key].id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azuread_service_principal.deploy[each.key].object_id
}

# ---- GitHub: the deploy environment and the one variable the workflows need ----------------------------------------------

resource "github_repository_environment" "deploy" {
  for_each    = local.deploy
  repository  = local.targets[each.key].repository
  environment = local.deploy_environment

  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_deployment_branch_policy" "deploy_main" {
  for_each         = local.deploy
  repository       = local.targets[each.key].repository
  environment_name = github_repository_environment.deploy[each.key].environment
  name             = "main"
}

resource "github_actions_variable" "deploy_client_id" {
  for_each      = local.deploy
  repository    = local.targets[each.key].repository
  variable_name = "DEPLOY_CLIENT_ID"
  value         = azuread_application.deploy[each.key].client_id
}

# Names the deploy workflows read (single source: the same map that scopes the deploy identity's rights).
locals {
  deploy_variables = merge([
    for k, d in local.deploy : {
      for name, value in merge(
        {
          PILOT_ACR_NAME = d.registry
          PILOT_API_APP  = d.container_apps[0]
        },
        length(d.container_apps) > 1 ? { PILOT_WEB_APP = d.container_apps[1] } : {},
        length(d.container_jobs) > 0 ? { PILOT_JOB_NAME = d.container_jobs[0] } : {},
        length(d.static_web_apps) > 0 ? { PILOT_SWA_WEB = d.static_web_apps[0] } : {},
        length(d.static_web_apps) > 1 ? { PILOT_SWA_LANDING = d.static_web_apps[1] } : {},
      ) : "${k}-${name}" => { target = k, name = name, value = value }
    }
  ]...)
}

resource "github_actions_variable" "deploy_names" {
  for_each      = local.deploy_variables
  repository    = local.targets[each.value.target].repository
  variable_name = each.value.name
  value         = each.value.value
}
