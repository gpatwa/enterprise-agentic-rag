# Private object storage for Discovery datasets: built subsets, their manifests and evaluation reports.
# Replaces the PostgreSQL option (owner decision, 2026-11-05). Nothing here is applied by automation.
#
# Access is Microsoft Entra only: shared keys are disabled and anonymous access is off. The apps' managed identity
# and any listed people get the data role; there is no key to leak. The OpenSearch index stays derived and can be
# rebuilt from a verified subset in this container.

resource "random_string" "data_suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_storage_account" "data" {
  # 3 to 24 lowercase letters and digits, globally unique.
  name                            = "${substr(replace(local.name, "-", ""), 0, 12)}data${random_string.data_suffix.result}"
  resource_group_name             = azurerm_resource_group.rg.name
  location                        = azurerm_resource_group.rg.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  tags                            = local.tags

  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }
}

# The container is created through the management plane so the stack never needs a storage key.
resource "azapi_resource" "datasets" {
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
  name      = "datasets"
  parent_id = "${azurerm_storage_account.data.id}/blobServices/default"

  body = {
    properties = {
      publicAccess = "None"
    }
  }
}

resource "azurerm_role_assignment" "apps_blob" {
  scope                = azurerm_storage_account.data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

resource "azurerm_role_assignment" "data_writers" {
  for_each             = toset(var.data_writer_object_ids)
  scope                = azurerm_storage_account.data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}
