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
