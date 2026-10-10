# infra/terraform/azure/iam.tf
# Managed Identities and Workload Identity — equivalent to AWS IAM + IRSA.
# Allows Kubernetes pods to securely access Azure resources without secrets.

# User-Assigned Managed Identity for the API pods
resource "azurerm_user_assigned_identity" "api_identity" {
  name                = "${var.cluster_name}-api-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# Grant the API identity access to the Storage Account (equivalent to S3 IAM policy)
resource "azurerm_role_assignment" "api_blob_contributor" {
  scope                = azurerm_storage_account.documents.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.api_identity.principal_id
}

# Federated Identity Credential — binds K8s Service Account to Azure Managed Identity
# This is the Azure equivalent of AWS IRSA (IAM Roles for Service Accounts)
resource "azurerm_federated_identity_credential" "api_federated" {
  name                = "api-federated-credential"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.api_identity.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject             = "system:serviceaccount:default:api-sa" # K8s namespace:serviceaccount
}

# Dedicated identity for the standalone analytics product. It is intentionally
# separate from the support API identity so analytics cannot inherit support
# storage permissions.
resource "azurerm_user_assigned_identity" "analytics_api_identity" {
  name                = "${var.cluster_name}-analytics-api-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = {
    Project     = "Enterprise-RAG"
    Product     = "Analytics"
    Environment = var.environment
  }
}

resource "azurerm_federated_identity_credential" "analytics_api_federated" {
  name                = "analytics-api-federated-credential"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.analytics_api_identity.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject             = "system:serviceaccount:default:analytics-api-sa"
}

# User-Assigned Managed Identity for Ray workers (ingestion pipeline)
resource "azurerm_user_assigned_identity" "ray_identity" {
  name                = "${var.cluster_name}-ray-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# Grant Ray workers read/write access to documents storage
resource "azurerm_role_assignment" "ray_blob_contributor" {
  scope                = azurerm_storage_account.documents.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.ray_identity.principal_id
}

# Federated Identity for Ray worker service account
resource "azurerm_federated_identity_credential" "ray_federated" {
  name                = "ray-federated-credential"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.ray_identity.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject             = "system:serviceaccount:default:ray-worker"
}
