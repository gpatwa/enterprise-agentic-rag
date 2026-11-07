# ---- observability (Container Apps needs a workspace; a daily cap bounds the bill) ----
resource "azurerm_log_analytics_workspace" "logs" {
  name                = "${local.name}-logs"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.5
  tags                = local.tags
}

# ---- registry (Basic, separate from every other product) ----
resource "azurerm_container_registry" "acr" {
  name                = replace("${var.prefix}${var.environment}acr", "-", "")
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "apps" {
  name                = "${local.name}-apps"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "apps_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

resource "azurerm_container_app_environment" "env" {
  name                       = "${local.name}-cae"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  # In a VNet so the API can reach the search VM privately. Changing this replaces the environment.
  infrastructure_subnet_id = azurerm_subnet.cae.id
  tags                     = local.tags

  # Azure creates this resource group itself. Unset in config, the provider plans a
  # replacement of the environment (and both apps) on every run.
  lifecycle {
    ignore_changes = [infrastructure_resource_group_name]
  }
}

# ---- API: internal ingress only, reachable from the web app inside the environment ----
resource "azurerm_container_app" "api" {
  name                         = "${local.name}-api"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  secret {
    name  = "opensearch-password"
    value = random_password.search.result
  }

  ingress {
    external_enabled = false
    target_port      = 8110
    transport        = "auto"
    # The web app's nginx proxies over plain HTTP inside the environment.
    allow_insecure_connections = true
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # Scale to zero: the demo is idle most of the time and the catalog is regenerated at start.
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "discovery-api"
      image  = "${azurerm_container_registry.acr.login_server}/discovery-api:${var.api_image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "DISCOVERY_ENVIRONMENT"
        value = "staging"
      }
      env {
        name  = "DISCOVERY_PROFILE"
        value = "pilot"
      }
      env {
        name  = "DISCOVERY_PORT"
        value = "8110"
      }
      env {
        name  = "DISCOVERY_FAKE_PROVIDER"
        value = "true"
      }
      env {
        name  = "DISCOVERY_NO_MODEL"
        value = "true"
      }
      # Search ranks through OpenSearch on the on-demand VM; when the VM is off the API serves the in-memory catalog.
      env {
        name  = "DISCOVERY_SEARCH_BACKEND"
        value = "opensearch"
      }
      env {
        name  = "DISCOVERY_OPENSEARCH_URL"
        value = "https://${local.search_vm_ip}:9200"
      }
      env {
        name  = "DISCOVERY_OPENSEARCH_USERNAME"
        value = "admin"
      }
      env {
        name        = "DISCOVERY_OPENSEARCH_PASSWORD"
        secret_name = "opensearch-password"
      }
      # The bundled demo certificate is self-signed; the port is reachable only from the apps' subnet.
      env {
        name  = "DISCOVERY_OPENSEARCH_VERIFY_TLS"
        value = "false"
      }
      env {
        name  = "DISCOVERY_FEATURE_VECTOR"
        value = "true"
      }
      env {
        name  = "DISCOVERY_FEATURE_HYBRID"
        value = "true"
      }
      # Short, so a stopped VM falls back to the in-memory catalog quickly.
      env {
        name  = "DISCOVERY_REQUEST_TIMEOUT_SECONDS"
        value = "2"
      }
      # Selects the apps' user-assigned identity when the API asks for a managed-identity token (Blob, Azure OpenAI).
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.apps.client_id
      }
      # Entra bearer-token validation; empty (so no change to the API) unless enable_api_auth is true.
      dynamic "env" {
        for_each = local.api_auth_env
        content {
          name  = env.key
          value = env.value
        }
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8110
        path      = "/health"
      }
    }
  }

  depends_on = [azurerm_role_assignment.apps_acr_pull]

  # Azure fills this in on a consumption-only environment; unset, the provider plans a diff every run.
  lifecycle {
    ignore_changes = [workload_profile_name]
  }
}

# ---- Sign-in: Entra app registration; only the listed accounts may sign in ----
locals {
  # Known before the web app exists, so the redirect URI does not depend on it.
  web_fqdn = "${local.name}-web.${azurerm_container_app_environment.env.default_domain}"
}

resource "azuread_application" "web" {
  display_name     = "${local.name}-web"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  # Container Apps built-in authentication (easy-auth) callback. Unchanged.
  web {
    redirect_uris = ["https://${local.web_fqdn}/.auth/login/aad/callback"]
    implicit_grant {
      id_token_issuance_enabled = true
    }
  }

  # The single-page app (MSAL) signs in silently on the same origin and asks for an access token for this same
  # app. A separate platform from `web` so it cannot collide with the easy-auth callback. No wildcard. The provider
  # requires the trailing slash on a root URI, so the web app must send exactly `<origin>/` as its redirect URI.
  single_page_application {
    redirect_uris = ["https://${local.web_fqdn}/"]
  }

  # This registration is also the API. Version 2 access tokens carry aud = the client id (a GUID) and
  # iss = https://login.microsoftonline.com/<tenant>/v2.0, which is what services/discovery-api validates.
  # Left unset (null) Entra issues version 1 tokens (aud = api://<id>, iss = sts.windows.net) and the API refuses them.
  api {
    requested_access_token_version = 2

    oauth2_permission_scope {
      id                         = random_uuid.access_as_user.result
      value                      = "access_as_user"
      type                       = "User"
      enabled                    = true
      admin_consent_display_name = "Use the Discovery demo API"
      admin_consent_description  = "Allows the Discovery demo web app to call the Discovery API as the signed-in user."
      user_consent_display_name  = "Use the Discovery demo API"
      user_consent_description   = "Allows the Discovery demo web app to call the Discovery API as you."
    }
  }

  # The identifier URI api://<client_id> contains the client id, which exists only after creation, so it is its own
  # resource (azuread_application_identifier_uri) and the application must not fight it.
  lifecycle {
    ignore_changes = [identifier_uris]
  }
}

resource "random_uuid" "access_as_user" {}

resource "azuread_application_identifier_uri" "web" {
  application_id = azuread_application.web.id
  identifier_uri = "api://${azuread_application.web.client_id}"
}

resource "azuread_service_principal" "web" {
  client_id                    = azuread_application.web.client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.current.object_id]

  # Fail closed: the pilot is never open to everyone, and an empty list must be a plan error, not an empty app.
  lifecycle {
    precondition {
      condition     = length(local.signin_object_ids) > 0
      error_message = "Name at least one account in access (access.auto.tfvars) or allowed_user_object_ids."
    }
  }
}

# Admin consent for the app's own scope, so the signed-in user is never shown a consent screen by the silent
# MSAL sign-in. Consent for all users of this one scope on this one app; nothing else is granted.
resource "azuread_service_principal_delegated_permission_grant" "web_self" {
  service_principal_object_id          = azuread_service_principal.web.object_id
  resource_service_principal_object_id = azuread_service_principal.web.object_id
  claim_values                         = ["access_as_user"]

  depends_on = [azuread_application_identifier_uri.web]
}

resource "azuread_app_role_assignment" "web_users" {
  for_each            = local.signin_object_ids
  app_role_id         = "00000000-0000-0000-0000-000000000000" # default access
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.web.object_id
}

# The auth config reads the client secret from a Container App secret. It expires and is rotated by re-applying.
resource "azuread_application_password" "web" {
  application_id    = azuread_application.web.id
  display_name      = "${local.name}-web-signin"
  end_date_relative = "4320h"
}

# ---- Web: the only public entry point; every request requires an assigned Entra account ----
resource "azurerm_container_app" "web" {
  name                         = "${local.name}-web"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  secret {
    name  = "entra-client-secret"
    value = azuread_application_password.web.value
  }

  ingress {
    external_enabled = true
    target_port      = 80
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }

    dynamic "ip_security_restriction" {
      for_each = { for i, c in var.allowed_cidrs : "allow-${i}" => c }
      content {
        name             = ip_security_restriction.key
        action           = "Allow"
        ip_address_range = ip_security_restriction.value
      }
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "discovery-web"
      image  = "${azurerm_container_registry.acr.login_server}/discovery-web:${var.web_image_tag}"
      cpu    = 0.25
      memory = "0.5Gi"

      # nginx proxies /api/ here and sends this as the Host header, which Container Apps uses to route.
      env {
        name  = "DISCOVERY_API_HOST"
        value = azurerm_container_app.api.ingress[0].fqdn
      }
    }
  }

  depends_on = [azurerm_role_assignment.apps_acr_pull]

  # Azure fills this in on a consumption-only environment; unset, the provider plans a diff every run.
  lifecycle {
    ignore_changes = [workload_profile_name]
  }
}

# Container Apps built-in authentication (azurerm 3.x has no resource for it).
# Unauthenticated requests are redirected to the Entra sign-in page; nothing is served without a session.
resource "azapi_resource" "web_auth" {
  type      = "Microsoft.App/containerApps/authConfigs@2024-03-01"
  name      = "current"
  parent_id = azurerm_container_app.web.id

  body = {
    properties = {
      platform = {
        enabled = true
      }
      globalValidation = {
        unauthenticatedClientAction = "RedirectToLoginPage"
        redirectToProvider          = "azureactivedirectory"
      }
      identityProviders = {
        azureActiveDirectory = {
          enabled = true
          registration = {
            clientId                = azuread_application.web.client_id
            clientSecretSettingName = "entra-client-secret"
            openIdIssuer            = "https://login.microsoftonline.com/${data.azuread_client_config.current.tenant_id}/v2.0"
          }
          validation = {
            allowedAudiences = [azuread_application.web.client_id]
          }
        }
      }
      login = {
        preserveUrlFragmentsForLogins = false
      }
    }
  }
}

# ---- a budget so the pilot cannot surprise anyone ----
resource "azurerm_consumption_budget_resource_group" "budget" {
  count             = length(var.budget_emails) > 0 ? 1 : 0
  name              = "${local.name}-budget"
  resource_group_id = azurerm_resource_group.rg.id
  amount            = var.monthly_budget_usd
  time_grain        = "Monthly"

  time_period {
    start_date = "2026-11-01T00:00:00Z"
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    contact_emails = var.budget_emails
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    contact_emails = var.budget_emails
  }
}
