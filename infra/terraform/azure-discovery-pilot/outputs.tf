output "web_url" {
  value = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "registry_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "resource_group" {
  value = azurerm_resource_group.rg.name
}

output "signin_app_client_id" {
  value = azuread_application.web.client_id
}

output "search_vm_name" {
  value = azurerm_linux_virtual_machine.search.name
}

output "search_vm_private_ip" {
  value = local.search_vm_ip
}

output "data_storage_account" {
  value = azurerm_storage_account.data.name
}

output "data_container" {
  value = azapi_resource.datasets.name
}

output "github_repository" {
  value = var.github_repository
}

# Everything the GitHub workflows need as repository variables. None of it is secret (identifiers and names only; the
# identity signs in with OIDC, so there is no client secret). `make discovery-repo-vars` reads this.
output "github_actions_variables" {
  value = merge(
    {
      DISCOVERY_AZURE_CLIENT_ID       = azuread_application.github_vm.client_id
      DISCOVERY_AZURE_TENANT_ID       = data.azuread_client_config.current.tenant_id
      DISCOVERY_AZURE_SUBSCRIPTION_ID = data.azurerm_client_config.current.subscription_id
      DISCOVERY_RESOURCE_GROUP        = azurerm_resource_group.rg.name
      DISCOVERY_SEARCH_VM_NAME        = azurerm_linux_virtual_machine.search.name
    },
    local.web_build_env,
  )
}

output "api_auth_enabled" {
  value = var.enable_api_auth
}

output "azure_openai_endpoint" {
  value = var.enable_openai ? azurerm_cognitive_account.openai[0].endpoint : null
}

output "azure_openai_embedding_deployment" {
  value = var.enable_openai ? azurerm_cognitive_deployment.embedding[0].name : null
}
