terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.90"
    }
  }

  backend "local" {}
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

locals {
  resource_group_name = var.resource_group_name != "" ? var.resource_group_name : "${var.name}-rg"
  vm_name             = "${var.name}-vm"
  vnet_name           = "${var.name}-vnet"
  subnet_name         = "${var.name}-subnet"
  nic_name            = "${var.name}-nic"
  public_ip_name      = "${var.name}-ip"
  nsg_name            = "${var.name}-nsg"
}

resource "azurerm_resource_group" "dev" {
  name     = local.resource_group_name
  location = var.location

  tags = merge(var.tags, {
    Environment = "remote-dev"
    ManagedBy   = "Terraform"
  })
}

resource "azurerm_virtual_network" "dev" {
  name                = local.vnet_name
  location            = azurerm_resource_group.dev.location
  resource_group_name = azurerm_resource_group.dev.name
  address_space       = [var.vnet_cidr]
}

resource "azurerm_subnet" "dev" {
  name                 = local.subnet_name
  resource_group_name  = azurerm_resource_group.dev.name
  virtual_network_name = azurerm_virtual_network.dev.name
  address_prefixes     = [var.subnet_cidr]
}

resource "azurerm_network_security_group" "dev" {
  name                = local.nsg_name
  location            = azurerm_resource_group.dev.location
  resource_group_name = azurerm_resource_group.dev.name

  security_rule {
    name                       = "allow-ssh-from-developer"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.ssh_source_cidr
    destination_address_prefix = "*"
  }

  tags = var.tags
}

resource "azurerm_public_ip" "dev" {
  name                = local.public_ip_name
  location            = azurerm_resource_group.dev.location
  resource_group_name = azurerm_resource_group.dev.name
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = var.tags
}

resource "azurerm_network_interface" "dev" {
  name                = local.nic_name
  location            = azurerm_resource_group.dev.location
  resource_group_name = azurerm_resource_group.dev.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.dev.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.dev.id
  }

  tags = var.tags
}

resource "azurerm_network_interface_security_group_association" "dev" {
  network_interface_id      = azurerm_network_interface.dev.id
  network_security_group_id = azurerm_network_security_group.dev.id
}

resource "azurerm_linux_virtual_machine" "dev" {
  name                = local.vm_name
  resource_group_name = azurerm_resource_group.dev.name
  location            = azurerm_resource_group.dev.location
  size                = var.vm_size
  admin_username      = var.admin_username

  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.dev.id]

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.ssh_public_key
  }

  os_disk {
    name                 = "${local.vm_name}-os"
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = var.os_disk_size_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
    admin_username = var.admin_username
    ssh_public_key = var.ssh_public_key
  }))

  identity {
    type = "SystemAssigned"
  }

  boot_diagnostics {
    storage_account_uri = null
  }

  tags = merge(var.tags, {
    Role = "docker-remote-development"
  })
}

resource "azurerm_dev_test_global_vm_shutdown_schedule" "dev" {
  count = var.auto_shutdown_enabled ? 1 : 0

  virtual_machine_id    = azurerm_linux_virtual_machine.dev.id
  location              = azurerm_resource_group.dev.location
  enabled               = true
  daily_recurrence_time = var.auto_shutdown_time_utc
  timezone              = "UTC"

  notification_settings {
    enabled = false
  }
}
