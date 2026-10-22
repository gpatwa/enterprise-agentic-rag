output "api_url" {
  value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "web_url" {
  value = "https://${azurerm_static_web_app.web.default_host_name}"
}

output "static_web_app_deploy_token" {
  value     = azurerm_static_web_app.web.api_key
  sensitive = true
}

output "registry_login_server" {
  value = local.acr_login_server
}

output "postgres_host" {
  value = local.pg_host
}

output "entra_audience" {
  value = local.entra_audience
}

output "entra_api_client_id" {
  value = var.create_entra_app ? azuread_application.api[0].client_id : null
}

output "key_vault_name" {
  value = azurerm_key_vault.kv.name
}

output "landing_url" {
  value = "https://${azurerm_static_web_app.landing.default_host_name}"
}

output "landing_deploy_token" {
  value     = azurerm_static_web_app.landing.api_key
  sensitive = true
}
