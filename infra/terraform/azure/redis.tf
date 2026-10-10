# infra/terraform/azure/redis.tf
# Azure Cache for Redis — equivalent to AWS ElastiCache Redis.
# Basic tier for dev, Standard/Premium for production.

resource "azurerm_redis_cache" "main" {
  name                = "${var.cluster_name}-redis"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  capacity            = 0 # C0 = 250 MB (smallest)

  # Dev: Basic C0 (~$16/mo) — no replication
  # Prod: Standard C1+ (replication) or Premium P1+ (VNet integration)
  family   = "C"
  sku_name = "Basic" # Dev: Basic (prod: Standard or Premium)

  non_ssl_port_enabled = false # Force TLS (matches AWS transit encryption)
  minimum_tls_version  = "1.2"
  # SECURITY: Set to false for production (use private endpoint below)
  public_network_access_enabled = var.environment == "prod" ? false : true

  redis_configuration {
    # Maxmemory policy for cache eviction
    maxmemory_policy = "allkeys-lru"
  }

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# For production: Private Endpoint to keep Redis off the public internet
# resource "azurerm_private_endpoint" "redis" {
#   name                = "${var.cluster_name}-redis-pe"
#   location            = azurerm_resource_group.main.location
#   resource_group_name = azurerm_resource_group.main.name
#   subnet_id           = azurerm_subnet.redis.id
#
#   private_service_connection {
#     name                           = "redis-psc"
#     private_connection_resource_id = azurerm_redis_cache.main.id
#     subresource_names              = ["redisCache"]
#     is_manual_connection           = false
#   }
# }
