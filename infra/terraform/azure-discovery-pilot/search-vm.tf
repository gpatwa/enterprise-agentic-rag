# ---- On-demand OpenSearch VM: private network, no inbound from the internet, no SSH ----
locals {
  search_vm_ip = cidrhost(var.search_subnet_cidr, 4)
}

resource "azurerm_virtual_network" "net" {
  name                = "${local.name}-vnet"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = [var.vnet_cidr]
  tags                = local.tags
}

# The Container Apps environment subnet: /23 is the documented minimum for a consumption-only environment.
resource "azurerm_subnet" "cae" {
  name                 = "cae"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.net.name
  address_prefixes     = [var.cae_subnet_cidr]
}

resource "azurerm_subnet" "search" {
  name                 = "search"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.net.name
  address_prefixes     = [var.search_subnet_cidr]
}

resource "azurerm_network_security_group" "search" {
  name                = "${local.name}-search-nsg"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags

  # Only the apps' subnet may reach OpenSearch.
  security_rule {
    name                       = "allow-opensearch-from-apps"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "9200"
    source_address_prefix      = var.cae_subnet_cidr
    destination_address_prefix = "*"
  }

  # Explicit deny, so nothing else in the VNet or on the internet gets in. This includes SSH.
  security_rule {
    name                       = "deny-all-other-inbound"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "search" {
  subnet_id                 = azurerm_subnet.search.id
  network_security_group_id = azurerm_network_security_group.search.id
}

# Outbound only: first boot pulls packages and the OpenSearch image. The NSG denies all inbound to it.
resource "azurerm_public_ip" "search" {
  name                = "${local.name}-search-ip"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_network_interface" "search" {
  name                = "${local.name}-search-nic"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags

  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.search.id
    private_ip_address_allocation = "Static"
    private_ip_address            = local.search_vm_ip
    public_ip_address_id          = azurerm_public_ip.search.id
  }
}

# OpenSearch's first-start admin password. It lands in Terraform state, the VM custom data and an app secret.
resource "random_password" "search" {
  length           = 28
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
  special          = true
  override_special = "!#-_."
}

# Azure requires an SSH key on a Linux VM with password login disabled. This one is never used and no
# NSG rule allows SSH, so the VM is administered with `az vm run-command` only.
resource "tls_private_key" "unused_ssh" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "azurerm_linux_virtual_machine" "search" {
  name                            = "${local.name}-search"
  location                        = azurerm_resource_group.rg.location
  resource_group_name             = azurerm_resource_group.rg.name
  size                            = var.search_vm_size
  admin_username                  = "discoveryadmin"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.search.id]
  tags                            = local.tags

  admin_ssh_key {
    username   = "discoveryadmin"
    public_key = tls_private_key.unused_ssh.public_key_openssh
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 64
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/search-vm.cloud-init.tftpl", {
    private_ip     = local.search_vm_ip
    admin_password = random_password.search.result
  }))
}

# A cost guard: deallocate every night. There is no automatic start; use the start/stop workflow or `az vm start`.
resource "azurerm_dev_test_global_vm_shutdown_schedule" "search" {
  virtual_machine_id    = azurerm_linux_virtual_machine.search.id
  location              = azurerm_resource_group.rg.location
  enabled               = true
  daily_recurrence_time = var.search_shutdown_time
  timezone              = "UTC"

  notification_settings {
    enabled = false
  }
}
