# infra/terraform/azure/dns.tf
# Azure DNS Public Zone for patwa-rag-platform.com
#
# Previously created manually. Brought under Terraform so the zone and records
# are destroyed cleanly with the rest of the infra.
#
# After AKS + ingress-nginx are deployed, the ingress Load Balancer gets a
# public IP. Set var.ingress_ip to that IP so the A record stays current.
#
# To import the existing zone:
#   Run: ./scripts/terraform_import_azure.sh
#
# Nameservers: after first apply, copy the NS records shown in
# `terraform output dns_nameservers` into your domain registrar.

resource "azurerm_dns_zone" "main" {
  name                = var.dns_zone_name
  resource_group_name = azurerm_resource_group.main.name

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# api.patwa-rag-platform.com → ingress Load Balancer public IP
# Only created when ingress_ip is set (empty during first apply before cluster exists).
resource "azurerm_dns_a_record" "api" {
  count               = var.ingress_ip != "" ? 1 : 0
  name                = "api"
  zone_name           = azurerm_dns_zone.main.name
  resource_group_name = azurerm_resource_group.main.name
  ttl                 = 300
  records             = [var.ingress_ip]
}

# www → api (simple redirect via CNAME)
resource "azurerm_dns_cname_record" "www" {
  count               = var.ingress_ip != "" ? 1 : 0
  name                = "www"
  zone_name           = azurerm_dns_zone.main.name
  resource_group_name = azurerm_resource_group.main.name
  ttl                 = 300
  record              = "api.${var.dns_zone_name}"
}
