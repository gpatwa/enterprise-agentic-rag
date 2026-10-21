variable "prefix" {
  type    = string
  default = "compass"
}

variable "environment" {
  type    = string
  default = "pilot"
}

variable "location" {
  type    = string
  default = "eastus"
}

variable "image_tag" {
  description = "Tag of compass-analytics-api in the registry (the deploy workflow pushes the commit SHA)."
  type        = string
}

variable "existing_acr_login_server" {
  description = "Reuse an existing registry (for example the platform's ACR) instead of creating a Basic one. Leave empty to create."
  type        = string
  default     = ""
}

variable "existing_acr_id" {
  description = "Resource ID of the existing registry, for the AcrPull role. Required when existing_acr_login_server is set."
  type        = string
  default     = ""
}

variable "postgres_admin_user" {
  type    = string
  default = "analyticsadmin"
}

variable "postgres_admin_password" {
  type      = string
  sensitive = true
}

variable "postgres_readonly_password" {
  description = "Password of the read-only warehouse role created by bootstrap.sql."
  type        = string
  sensitive   = true
}

variable "run_id_key" {
  description = "At least 32 random bytes (hex); required by the API outside dev (security finding F-02)."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.run_id_key) >= 32
    error_message = "run_id_key must be at least 32 characters."
  }
}

variable "api_key" {
  description = "Shared API key sent by the web app; identity comes from the Entra bearer token."
  type        = string
  sensitive   = true
}

variable "create_openai" {
  description = "Create an Azure OpenAI account and a gpt-4o-mini deployment (needs Azure OpenAI access in the subscription)."
  type        = bool
  default     = false
}

variable "openai_location" {
  type    = string
  default = "eastus"
}

variable "openai_capacity" {
  description = "Thousands of tokens per minute for the deployment."
  type        = number
  default     = 10
}

variable "azure_openai_endpoint" {
  description = "An existing Azure OpenAI endpoint, when create_openai is false."
  type        = string
  default     = ""
}

variable "azure_openai_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "azure_openai_deployment" {
  type    = string
  default = "gpt-4o-mini"
}

variable "create_entra_app" {
  description = "Create the API app registration with the Analytics.Analyst and Analytics.Reviewer app roles (needs directory permissions)."
  type        = bool
  default     = true
}

variable "entra_audience" {
  description = "The API's audience when create_entra_app is false (for example api://<client-id>)."
  type        = string
  default     = ""
}

variable "analytics_tenant_map" {
  description = "JSON object: Entra tenant ID -> analytics tenant ID. Defaults to this directory -> tenant-a."
  type        = string
  default     = ""
}

variable "v2_contracts" {
  type    = string
  default = "sales-core@v1"
}

variable "min_cohort" {
  description = "Minimum group size (security finding F-03). Empty disables it; the security persona recommends 10."
  type        = string
  default     = "10"
}

variable "cors_origins" {
  description = "Extra allowed origins; the Static Web App's own hostname is always added."
  type        = list(string)
  default     = []
}

variable "monthly_budget_usd" {
  type    = number
  default = 100
}

variable "budget_emails" {
  type    = list(string)
  default = []
}
