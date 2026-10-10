output "resource_group_name" {
  description = "Resource group containing the remote development environment."
  value       = azurerm_resource_group.dev.name
}

output "vm_name" {
  description = "Remote Docker VM name."
  value       = azurerm_linux_virtual_machine.dev.name
}

output "public_ip_address" {
  description = "SSH endpoint for the remote Docker VM."
  value       = azurerm_public_ip.dev.ip_address
}

output "private_ip_address" {
  description = "Private address of the remote Docker VM."
  value       = azurerm_network_interface.dev.private_ip_address
}

output "ssh_command" {
  description = "Human-readable SSH command; the lifecycle script supplies the key path."
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.dev.ip_address}"
}
