# infra/terraform/azure/keyvault.tf
# Azure Key Vault — secure storage for application secrets.
# Equivalent to AWS Secrets Manager.
#
# All sensitive values (DB password, JWT secret, API keys) are stored
# here instead of plain Kubernetes Secrets.  The API pods retrieve
# them at runtime via Workload Identity + DefaultAzureCredential.

resource "azurerm_key_vault" "main" {
  name                       = "${var.cluster_name}-kv"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false # Dev: false to allow quick cleanup. Prod: true

  # Allow the Terraform operator (current user/SP) to manage secrets
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Get", "List", "Set", "Delete", "Purge", "Recover",
    ]
  }

  # Allow the API pod (Workload Identity) to read secrets at runtime
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = azurerm_user_assigned_identity.api_identity.principal_id

    secret_permissions = [
      "Get", "List",
    ]
  }

  # Allow the Ray worker (Workload Identity) to read secrets at runtime
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = azurerm_user_assigned_identity.ray_identity.principal_id

    secret_permissions = [
      "Get", "List",
    ]
  }

  # Analytics API can read only the secrets needed by its provider adapters.
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = azurerm_user_assigned_identity.analytics_api_identity.principal_id

    secret_permissions = [
      "Get", "List",
    ]
  }

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# Secrets — stored in Key Vault, never in plain K8s Secrets
# ---------------------------------------------------------------------------

resource "azurerm_key_vault_secret" "db_password" {
  name         = "db-password"
  value        = var.db_password
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "jwt_secret_key" {
  name         = "jwt-secret-key"
  value        = var.jwt_secret_key
  key_vault_id = azurerm_key_vault.main.id
}

# Redis primary access key (from the managed Redis resource)
resource "azurerm_key_vault_secret" "redis_primary_key" {
  name         = "redis-primary-key"
  value        = azurerm_redis_cache.main.primary_access_key
  key_vault_id = azurerm_key_vault.main.id
}

# Neo4j password
resource "azurerm_key_vault_secret" "neo4j_password" {
  name         = "neo4j-password"
  value        = var.neo4j_password
  key_vault_id = azurerm_key_vault.main.id
}

# OpenAI API key (only if provided)
resource "azurerm_key_vault_secret" "openai_api_key" {
  count        = var.openai_api_key != "" ? 1 : 0
  name         = "openai-api-key"
  value        = var.openai_api_key
  key_vault_id = azurerm_key_vault.main.id
}

# Google Gemini API key — for multimodal embeddings (only if provided)
resource "azurerm_key_vault_secret" "gemini_api_key" {
  count        = var.gemini_api_key != "" ? 1 : 0
  name         = "gemini-api-key"
  value        = var.gemini_api_key
  key_vault_id = azurerm_key_vault.main.id
}

# Tavily API key — for web search tool (only if provided)
resource "azurerm_key_vault_secret" "tavily_api_key" {
  count        = var.tavily_api_key != "" ? 1 : 0
  name         = "tavily-api-key"
  value        = var.tavily_api_key
  key_vault_id = azurerm_key_vault.main.id
}
