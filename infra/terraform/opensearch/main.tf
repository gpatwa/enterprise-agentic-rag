terraform {
  required_version = ">= 1.5.0"
}

locals {
  endpoint = "${var.scheme}://${var.host}:${var.port}"
}

output "endpoint" {
  value       = local.endpoint
  description = "Provider endpoint consumed by OPENSEARCH_URL."
}

output "index_alias" {
  value = var.index_alias
}
