# infra/terraform/azure/servicebus.tf
# Azure Service Bus — managed message broker for async task queuing.
#
# NOTE: This resource has NO references in the application code and appears
# to have been created manually. Brought under Terraform management so it
# can be destroyed cleanly and won't be missed during teardown.
#
# Current use case: none (orphaned). If async document ingestion queuing
# is needed in future, this namespace is the right foundation.
#
# To remove: set var.servicebus_enabled = false and apply. Saves ~$0.10/day.
#
# To import the existing namespace:
#   Run: ./scripts/terraform_import_azure.sh

resource "azurerm_servicebus_namespace" "main" {
  count               = var.servicebus_enabled ? 1 : 0
  name                = "${var.cluster_name}-sb"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  # Standard tier: ~$10/month, supports topics + queues.
  # Basic tier: ~$0.05/month but only queues (no topics/subscriptions).
  sku = var.servicebus_sku # Default: "Standard"

  # Minimum TLS for in-transit security
  minimum_tls_version = "1.2"

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# Document ingestion queue — ready for use when async ingestion is wired up.
resource "azurerm_servicebus_queue" "ingestion" {
  count        = var.servicebus_enabled ? 1 : 0
  name         = "document-ingestion"
  namespace_id = azurerm_servicebus_namespace.main[0].id

  # Dead-letter after 10 failed deliveries
  max_delivery_count = 10

  # Messages expire after 1 day if not processed
  default_message_ttl = "P1D"
}
