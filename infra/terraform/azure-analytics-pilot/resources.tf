# ---- observability (Container Apps needs a workspace; a daily cap bounds the bill) ----
resource "azurerm_log_analytics_workspace" "logs" {
  name                = "${local.name}-logs"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 1
  tags                = local.tags
}

# ---- registry (Basic, unless an existing one is reused) ----
resource "azurerm_container_registry" "acr" {
  count               = var.existing_acr_login_server == "" ? 1 : 0
  name                = replace("${var.prefix}${var.environment}acr", "-", "")
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

# ---- PostgreSQL Flexible Server, Burstable B1ms: control store and the pilot warehouse ----
# Public endpoint with TLS required and the "Azure services" rule: cheaper than a VNet and private endpoint. Tighten for production.
resource "azurerm_postgresql_flexible_server" "pg" {
  name                          = "${local.name}-pg"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = var.postgres_location
  version                       = "16"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  administrator_login           = var.postgres_admin_user
  administrator_password        = var.postgres_admin_password
  public_network_access_enabled = true
  tags                          = local.tags

  lifecycle {
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.pg.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "control" {
  name      = "analytics_control"
  server_id = azurerm_postgresql_flexible_server.pg.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_postgresql_flexible_server_database" "warehouse" {
  name      = "analytics_warehouse"
  server_id = azurerm_postgresql_flexible_server.pg.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# ---- secrets ----
resource "azurerm_key_vault" "kv" {
  name                       = substr(replace("${var.prefix}-${var.environment}-kv", "_", "-"), 0, 24)
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  tags                       = local.tags
}

resource "azurerm_role_assignment" "deployer_kv" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

locals {
  secrets = merge(
    {
      "analytics-run-id-key"     = var.run_id_key
      "analytics-api-key"        = var.api_key
      "analytics-control-db-url" = local.control_db_url
      "analytics-db-url"         = local.warehouse_db_url
    },
    local.has_openai_key ? { "azure-openai-api-key" = local.openai_key } : {}
  )
}

resource "azurerm_key_vault_secret" "secret" {
  for_each     = nonsensitive(toset(keys(local.secrets)))
  name         = each.value
  value        = local.secrets[each.value]
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.deployer_kv]
}

# ---- identity of the API and the purge job ----
resource "azurerm_user_assigned_identity" "api" {
  name                = "${local.name}-analytics-api"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags
}

resource "azurerm_role_assignment" "api_acr_pull" {
  scope                = var.existing_acr_login_server == "" ? azurerm_container_registry.acr[0].id : var.existing_acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "api_kv_read" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

# ---- Azure OpenAI (optional) ----
resource "azurerm_cognitive_account" "openai" {
  count                 = var.create_openai ? 1 : 0
  name                  = "${local.name}-openai"
  location              = var.openai_location
  resource_group_name   = azurerm_resource_group.rg.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "${local.name}-openai"
  tags                  = local.tags
}

resource "azurerm_cognitive_deployment" "intent" {
  count                = var.create_openai ? 1 : 0
  name                 = var.azure_openai_deployment
  cognitive_account_id = azurerm_cognitive_account.openai[0].id
  model {
    format  = "OpenAI"
    name    = var.azure_openai_model
    version = var.azure_openai_model_version
  }
  scale {
    type     = "GlobalStandard"
    capacity = var.openai_capacity
  }
}

# ---- Entra ID app registration for the API (optional) ----
resource "azuread_application" "api" {
  count            = var.create_entra_app ? 1 : 0
  display_name     = "${local.name}-analytics-api"
  identifier_uris  = [local.entra_audience]
  sign_in_audience = "AzureADMyOrg"

  api {
    requested_access_token_version = 2

    # A delegated scope, so tokens issued to signed-in people carry `scp`; an app-only token gets no purposes from the API.
    oauth2_permission_scope {
      id                         = "0e5a2c64-6a3b-4a60-9a4d-6c1f8d2b7e11"
      value                      = "access_as_user"
      type                       = "User"
      admin_consent_display_name = "Use Compass analytics as the signed-in user"
      admin_consent_description  = "Allows the app to ask governed analytics questions as the signed-in user."
      user_consent_display_name  = "Use Compass analytics as you"
      user_consent_description   = "Allows the app to ask governed analytics questions as you."
      enabled                    = true
    }
  }

  optional_claims {
    access_token {
      name = "idtyp"
    }
    access_token {
      name = "preferred_username"
    }
  }

  app_role {
    allowed_member_types = ["User", "Application"]
    description          = "Read paused reviews and write notes for reviewers. Cannot ask questions or decide reviews."
    display_name         = "Analytics review assistant"
    id                   = "7c2d9e41-3b5a-4f68-8a1e-5d0b6c4f9a27"
    value                = "Analytics.ReviewAssistant"
    enabled              = true
  }

  app_role {
    allowed_member_types = ["User"]
    description          = "Ask governed analytics questions (purpose: analytics)."
    display_name         = "Analytics analyst"
    id                   = "1b4f816e-5eaf-48b9-8613-7923830595ad"
    value                = "Analytics.Analyst"
    enabled              = true
  }

  app_role {
    allowed_member_types = ["User"]
    description          = "Decide paused analytics reviews (never your own)."
    display_name         = "Analytics reviewer"
    id                   = "4e3f6c2a-8d1b-4f5e-9a7c-2b6d8e0f1a3c"
    value                = "Analytics.Reviewer"
    enabled              = true
  }
}

resource "azuread_service_principal" "api" {
  count                        = var.create_entra_app ? 1 : 0
  client_id                    = azuread_application.api[0].client_id
  app_role_assignment_required = true
}

# ---- the public landing page (static, Free tier) ----
resource "azurerm_static_web_app" "landing" {
  name                = "${local.name}-landing"
  resource_group_name = azurerm_resource_group.rg.name
  location            = "eastus2"
  sku_tier            = "Free"
  sku_size            = "Free"
  tags                = local.tags
}

# ---- the web app (static, Free tier) ----
resource "azurerm_static_web_app" "web" {
  name                = "${local.name}-analytics-web"
  resource_group_name = azurerm_resource_group.rg.name
  location            = "eastus2" # Static Web Apps is offered in a few regions; the content is served globally
  sku_tier            = "Free"
  sku_size            = "Free"
  tags                = local.tags
}

# ---- Container Apps ----
resource "azurerm_container_app_environment" "env" {
  name                       = "${local.name}-cae"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  tags                       = local.tags
}

locals {
  image      = "${local.acr_login_server}/compass-analytics-api:${var.image_tag}"
  tenant_map = var.analytics_tenant_map != "" ? var.analytics_tenant_map : jsonencode({ (data.azurerm_client_config.current.tenant_id) = "tenant-a" })
  cors       = join(",", concat(["https://${azurerm_static_web_app.web.default_host_name}"], var.cors_origins))
  secret_env_map = {
    ANALYTICS_RUN_ID_KEY     = "analytics-run-id-key"
    ANALYTICS_API_KEY        = "analytics-api-key"
    ANALYTICS_CONTROL_DB_URL = "analytics-control-db-url"
    ANALYTICS_DB_URL         = "analytics-db-url"
  }
  openai_secret_env = local.has_openai_key ? { AZURE_OPENAI_API_KEY = "azure-openai-api-key" } : {}
  all_secret_env    = merge(local.secret_env_map, local.openai_secret_env)
  plain_env = {
    ENV                           = "prod"
    ANALYTICS_V2_ENABLED          = "true"
    ANALYTICS_V2_CONTRACTS        = var.v2_contracts
    ANALYTICS_MIGRATE_ON_START    = "true"
    ANALYTICS_V1_ENABLED          = "false"
    ANALYTICS_LEASE_SECONDS       = "120"
    ANALYTICS_CORS_ORIGINS        = local.cors
    ANALYTICS_MIN_COHORT          = var.min_cohort
    AZURE_OPENAI_ENDPOINT         = local.openai_endpoint
    AZURE_OPENAI_DEPLOYMENT       = var.azure_openai_deployment
    AZURE_OPENAI_API_VERSION      = var.azure_openai_api_version
    AZURE_OPENAI_REASONING_EFFORT = var.azure_openai_reasoning_effort
    ENTRA_TENANT_ID               = data.azurerm_client_config.current.tenant_id
    # v2 access tokens carry the application's client id as `aud` (the api:// URI is only the scope's resource name).
    ENTRA_AUDIENCE       = var.create_entra_app ? azuread_application.api[0].client_id : var.entra_audience
    ANALYTICS_TENANT_MAP = local.tenant_map
  }
}

resource "azurerm_container_app" "api" {
  name                         = "${local.name}-analytics-api"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }

  registry {
    server   = local.acr_login_server
    identity = azurerm_user_assigned_identity.api.id
  }

  dynamic "secret" {
    for_each = local.all_secret_env
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.api.id
      key_vault_secret_id = azurerm_key_vault_secret.secret[secret.value].versionless_id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8090
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # Exactly one replica: quota state and the answer-row handoff are process-local in the pilot.
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "analytics-api"
      image  = local.image
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.all_secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8090
        path      = "/health"
      }
    }
  }

  depends_on = [azurerm_role_assignment.api_acr_pull, azurerm_role_assignment.api_kv_read]
}

# Hourly retention purge (policy values when runs end; plans and links after 30 days). Billed per execution second.
resource "azurerm_container_app_job" "purge" {
  name                         = "${local.name}-analytics-purge"
  location                     = azurerm_resource_group.rg.location
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  replica_timeout_in_seconds   = 300
  replica_retry_limit          = 1
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }

  registry {
    server   = local.acr_login_server
    identity = azurerm_user_assigned_identity.api.id
  }

  secret {
    name                = "analytics-control-db-url"
    identity            = azurerm_user_assigned_identity.api.id
    key_vault_secret_id = azurerm_key_vault_secret.secret["analytics-control-db-url"].versionless_id
  }

  schedule_trigger_config {
    cron_expression          = "17 * * * *"
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "purge"
      image   = local.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "app.jobs.purge"]
      env {
        name        = "ANALYTICS_CONTROL_DB_URL"
        secret_name = "analytics-control-db-url"
      }
    }
  }

  depends_on = [azurerm_role_assignment.api_acr_pull, azurerm_role_assignment.api_kv_read]
}

# ---- a budget so the pilot cannot surprise anyone ----
resource "azurerm_consumption_budget_resource_group" "budget" {
  count             = length(var.budget_emails) > 0 ? 1 : 0
  name              = "${local.name}-budget"
  resource_group_id = azurerm_resource_group.rg.id
  amount            = var.monthly_budget_usd
  time_grain        = "Monthly"

  time_period {
    start_date = "2026-10-01T00:00:00Z"
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

# Lets people mint a token for the pilot with `az account get-access-token --scope <audience>/.default` (Azure CLI's
# well-known client id). They still need an app role assignment; this only skips the consent prompt.
resource "azuread_application_pre_authorized" "azure_cli" {
  count                = var.create_entra_app ? 1 : 0
  application_id       = azuread_application.api[0].id
  authorized_client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
  permission_ids       = ["0e5a2c64-6a3b-4a60-9a4d-6c1f8d2b7e11"]
}
