# Discovery-owned Azure OpenAI: one account and one small embedding deployment, separate from the Compass account.
# Creating them makes no model call and costs nothing while idle (billing is per token). Embedding calls stay off in
# the API (DISCOVERY_NO_MODEL=true, DISCOVERY_EMBEDDING_PROVIDER unset = the local hashing embedder).
#
# Key authentication is disabled: the only way in is an Entra token, which the API's managed identity (and any person
# listed in openai_user_object_ids, using their own `az login`) obtains. There is no key to leak or rotate.

resource "random_string" "openai_suffix" {
  count   = var.enable_openai ? 1 : 0
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_cognitive_account" "openai" {
  count               = var.enable_openai ? 1 : 0
  name                = "${local.name}-openai"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  kind                = "OpenAI"
  sku_name            = "S0"
  # Required for Entra token authentication; globally unique, and a deleted account holds its name for a while,
  # hence the random suffix.
  custom_subdomain_name = "${local.name}-openai-${random_string.openai_suffix[0].result}"
  local_auth_enabled    = false
  tags                  = local.tags
}

resource "azurerm_cognitive_deployment" "embedding" {
  count                = var.enable_openai ? 1 : 0
  name                 = "text-embedding-3-small"
  cognitive_account_id = azurerm_cognitive_account.openai[0].id

  model {
    format  = "OpenAI"
    name    = "text-embedding-3-small"
    version = "1"
  }

  scale {
    type     = "GlobalStandard"
    capacity = var.embedding_capacity
  }
}

# The API's managed identity may call the models, not manage the account.
resource "azurerm_role_assignment" "apps_openai_user" {
  count                = var.enable_openai ? 1 : 0
  scope                = azurerm_cognitive_account.openai[0].id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

resource "azurerm_role_assignment" "people_openai_user" {
  for_each             = var.enable_openai ? toset(var.openai_user_object_ids) : toset([])
  scope                = azurerm_cognitive_account.openai[0].id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = each.value
}
