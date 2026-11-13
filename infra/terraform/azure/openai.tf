# infra/terraform/azure/openai.tf
# Azure OpenAI for the LLM and the 768-dimension embeddings, reached with Entra tokens (workload identity), so there is
# no provider API key to store, rotate or expire. Key (local) authentication is turned off on the account on purpose.
#
# The endpoint is deterministic (https://<custom subdomain>.openai.azure.com/), so the Helm values can name it and a test
# keeps the two in step. The subdomain is globally unique: if the apply reports it is taken, set openai_account_name.

locals {
  openai_account_name = var.openai_account_name != "" ? var.openai_account_name : "${var.cluster_name}-openai"
}

resource "azurerm_cognitive_account" "openai" {
  name                = local.openai_account_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  kind                = "OpenAI"
  sku_name            = "S0"

  # Required for Entra ID (token) authentication.
  custom_subdomain_name = local.openai_account_name

  # Keyless only: nothing can authenticate with an account key.
  local_auth_enabled = false

  public_network_access_enabled = var.allow_public_data_services

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

resource "azurerm_cognitive_deployment" "llm" {
  name                 = var.openai_llm_deployment
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.openai_llm_model
    version = var.openai_llm_model_version
  }

  scale {
    type     = var.openai_llm_sku
    capacity = var.openai_llm_capacity # thousands of tokens per minute
  }
}

resource "azurerm_cognitive_deployment" "embed" {
  name                 = var.openai_embed_deployment
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "text-embedding-3-small"
    version = "1"
  }

  scale {
    type     = "Standard"
    capacity = var.openai_embed_capacity
  }

  # Deployments on one account are created one at a time.
  depends_on = [azurerm_cognitive_deployment.llm]
}

# The identities that call the models: the API (and the support worker, which runs the same image) and the Ray workers.
resource "azurerm_role_assignment" "api_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.api_identity.principal_id
}

resource "azurerm_role_assignment" "ray_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.ray_identity.principal_id
}

# Developers who run the API locally against this account with their own `az login` (no key involved).
resource "azurerm_role_assignment" "developer_openai_user" {
  for_each             = toset(var.openai_user_principal_ids)
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = each.value
}
