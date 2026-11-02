output "web_url" {
  value = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "registry_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "resource_group" {
  value = azurerm_resource_group.rg.name
}
