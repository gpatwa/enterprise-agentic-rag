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
  tags                       = local.tags
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

      liveness_probe {
        transport = "HTTP"
        port      = 8110
        path      = "/health"
      }
    }
  }

  depends_on = [azurerm_role_assignment.apps_acr_pull]
}

# ---- Web: the only public entry point, limited to the allowed addresses ----
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
