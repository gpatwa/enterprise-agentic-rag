# infra/terraform/azure/postgres.tf
# Azure Database for PostgreSQL Flexible Server — equivalent to AWS Aurora Serverless v2.
# Burstable tier for dev, scalable to General Purpose for production.
#
# Note: Using public access with firewall rules for dev.
# For production, switch to VNet integration (delegated_subnet_id + private_dns_zone_id)
# in a region that supports it.

resource "azurerm_postgresql_flexible_server" "main" {
  name                   = "ragplatform-pgdb-central"
  resource_group_name    = azurerm_resource_group.main.name
  location               = "centralus" # eastus/eastus2/westus2 restricted for Postgres Burstable
  version                = "15"        # Match Aurora PostgreSQL 15
  administrator_login    = "ragadmin"
  administrator_password = var.db_password
  storage_mb             = 32768 # 32 GB (minimum for Burstable)
  backup_retention_days  = 7
  zone                   = "1"

  # Dev: Burstable B1ms (1 vCPU, 2 GB) — ~$13/mo
  # Prod: General Purpose D2s_v3 (2 vCPU, 8 GB) or higher
  sku_name = "B_Standard_B1ms"

  # Dev: public access with firewall (see firewall rules below)
  # Prod: use delegated_subnet_id + private_dns_zone_id for VNet integration
  public_network_access_enabled = true

  # High Availability — disabled for dev (enable for prod)
  # high_availability {
  #   mode = "ZoneRedundant"
  # }

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# Database within the server
resource "azurerm_postgresql_flexible_server_database" "ragdb" {
  name      = "ragdb"
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

# Firewall rule — allow Azure services (AKS pods communicate via Azure backbone)
# SECURITY: In production, remove this rule and use VNet integration instead
# by setting delegated_subnet_id + private_dns_zone_id on the server,
# and setting public_network_access_enabled = false.
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure" {
  count     = var.environment == "prod" ? 0 : 1 # Disabled in production
  name      = "allow-azure-services"
  server_id = azurerm_postgresql_flexible_server.main.id
  # 0.0.0.0 to 0.0.0.0 = allow Azure internal services
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# ---------------------------------------------------------------------------
# PRODUCTION: VNet integration for PostgreSQL (private networking)
# ---------------------------------------------------------------------------
# Uncomment and apply for production.  Requires the database subnet
# delegation already defined in vnet.tf.
#
# To migrate from public to private:
#   1. Set public_network_access_enabled = false on the server resource
#   2. Add delegated_subnet_id and private_dns_zone_id
#   3. Remove the firewall rules (count = 0 above)
#   4. Run terraform apply (this will recreate the server)
#
# resource "azurerm_postgresql_flexible_server" "main" {
#   ...
#   delegated_subnet_id           = azurerm_subnet.database.id
#   private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
#   public_network_access_enabled = false
# }
