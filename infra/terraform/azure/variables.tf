# infra/terraform/azure/variables.tf

variable "location" {
  description = "Azure region to deploy resources"
  type        = string
  default     = "eastus" # East US has good GPU availability and competitive pricing
}

variable "environment" {
  description = "Environment name (e.g., dev, prod)"
  type        = string
  default     = "prod"
}

variable "resource_group_name" {
  description = "Name of the Azure Resource Group"
  type        = string
  default     = "rag-platform-rg"
}

variable "cluster_name" {
  description = "Name of the AKS Cluster"
  type        = string
  default     = "rag-platform-aks"
}

variable "vnet_cidr" {
  description = "CIDR block for the VNet"
  type        = string
  default     = "10.0.0.0/16" # Same as AWS VPC for parity
}

variable "db_password" {
  description = "Administrator password for PostgreSQL Flexible Server"
  type        = string
  sensitive   = true
}

variable "acr_name" {
  description = "Name of the Azure Container Registry (must be globally unique, alphanumeric only)"
  type        = string
  default     = "ragplatformacr"
}

variable "jwt_secret_key" {
  description = "JWT signing secret for HS256 tokens"
  type        = string
  sensitive   = true
}

variable "neo4j_password" {
  description = "Password for Neo4j graph database"
  type        = string
  sensitive   = true
  default     = "password" # Override via tfvars for production
}

variable "openai_api_key" {
  description = "OpenAI API key (leave empty to skip Key Vault storage)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "gemini_api_key" {
  description = "Google Gemini API key for multimodal embeddings (leave empty to skip)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "tavily_api_key" {
  description = "Tavily API key for web search tool (leave empty to skip)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "kubernetes_version" {
  description = "Kubernetes version for AKS"
  type        = string
  default     = "1.29" # Match AWS EKS version for parity
}

# ─── Monitoring ──────────────────────────────────────────────────────────────

variable "log_retention_days" {
  description = "Log Analytics workspace retention in days (30 = minimum/free, max 730)"
  type        = number
  default     = 30
}

variable "log_daily_quota_gb" {
  description = "Log Analytics daily ingestion cap in GB (-1 = unlimited). Set low for dev to avoid surprise bills."
  type        = number
  default     = 1
}

# ─── DNS ─────────────────────────────────────────────────────────────────────

variable "dns_zone_name" {
  description = "Public DNS zone name (e.g. patwa-rag-platform.com)"
  type        = string
  default     = "patwa-rag-platform.com"
}

variable "ingress_ip" {
  description = "Public IP of the ingress Load Balancer. Set after first deploy: terraform output ingress_ip. Leave empty on initial apply."
  type        = string
  default     = ""
}

# ─── App Service ─────────────────────────────────────────────────────────────

variable "appservice_enabled" {
  description = "Set to false to destroy the App Service and Plan (saves ~$0.99/day). Currently unused by application code."
  type        = bool
  default     = true
}

variable "appservice_sku" {
  description = "App Service Plan SKU. B1 = Basic (~$13/mo). F1 = Free (limited). S1 = Standard (~$70/mo)."
  type        = string
  default     = "B1"
}

# ─── Container Apps ──────────────────────────────────────────────────────────

variable "containerapps_enabled" {
  description = "Set to false to destroy the Container Apps environment (saves ~$2.29/day). Currently unused by application code."
  type        = bool
  default     = true
}

# ─── Service Bus ─────────────────────────────────────────────────────────────

variable "servicebus_enabled" {
  description = "Set to false to destroy the Service Bus namespace (saves ~$0.10/day). Currently unused by application code."
  type        = bool
  default     = true
}

variable "servicebus_sku" {
  description = "Service Bus SKU. Basic = ~$0.05/mo (queues only). Standard = ~$10/mo (topics + queues)."
  type        = string
  default     = "Standard"
}
