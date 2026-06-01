# infra/terraform/azure/outputs.tf

output "aks_cluster_name" {
  description = "The name of the AKS cluster."
  value       = azurerm_kubernetes_cluster.aks.name
}

output "aks_cluster_endpoint" {
  description = "The endpoint (FQDN) for the AKS cluster's API server."
  value       = azurerm_kubernetes_cluster.aks.fqdn
}

output "postgres_fqdn" {
  description = "The FQDN for the PostgreSQL Flexible Server."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "postgres_database" {
  description = "The name of the PostgreSQL database."
  value       = azurerm_postgresql_flexible_server_database.ragdb.name
}

output "redis_hostname" {
  description = "The hostname for the Azure Cache for Redis."
  value       = azurerm_redis_cache.main.hostname
}

output "redis_ssl_port" {
  description = "The SSL port for the Azure Cache for Redis."
  value       = azurerm_redis_cache.main.ssl_port
}

output "redis_primary_key" {
  description = "The primary access key for Redis."
  value       = azurerm_redis_cache.main.primary_access_key
  sensitive   = true
}

output "storage_account_name" {
  description = "The name of the Azure Storage Account for documents."
  value       = azurerm_storage_account.documents.name
}

output "storage_container_name" {
  description = "The name of the Blob container for documents."
  value       = azurerm_storage_container.documents.name
}

output "acr_login_server" {
  description = "The login server URL for the Azure Container Registry."
  value       = azurerm_container_registry.acr.login_server
}

output "acr_name" {
  description = "The name of the Azure Container Registry."
  value       = azurerm_container_registry.acr.name
}

output "api_identity_client_id" {
  description = "Client ID of the API Managed Identity (for Workload Identity)."
  value       = azurerm_user_assigned_identity.api_identity.client_id
}

output "ray_identity_client_id" {
  description = "Client ID of the Ray Managed Identity (for Workload Identity)."
  value       = azurerm_user_assigned_identity.ray_identity.client_id
}

output "resource_group_name" {
  description = "The name of the resource group."
  value       = azurerm_resource_group.main.name
}

output "key_vault_name" {
  description = "The name of the Azure Key Vault."
  value       = azurerm_key_vault.main.name
}

output "key_vault_url" {
  description = "The URL of the Azure Key Vault (for AZURE_KEY_VAULT_URL env var)."
  value       = azurerm_key_vault.main.vault_uri
}

output "log_analytics_workspace_id" {
  description = "Resource ID of the Log Analytics workspace."
  value       = azurerm_log_analytics_workspace.main.id
}

output "log_analytics_workspace_name" {
  description = "Name of the Log Analytics workspace."
  value       = azurerm_log_analytics_workspace.main.name
}

output "dns_zone_name" {
  description = "The public DNS zone name."
  value       = azurerm_dns_zone.main.name
}

output "dns_nameservers" {
  description = "Nameservers to configure at your domain registrar."
  value       = azurerm_dns_zone.main.name_servers
}

output "appservice_url" {
  description = "Default hostname of the App Service (if enabled)."
  value       = var.appservice_enabled ? "https://${azurerm_linux_web_app.main[0].default_hostname}" : "disabled"
}

output "servicebus_namespace" {
  description = "Name of the Service Bus namespace (if enabled)."
  value       = var.servicebus_enabled ? azurerm_servicebus_namespace.main[0].name : "disabled"
}
