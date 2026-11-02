variable "prefix" {
  type    = string
  default = "discovery"
}

variable "environment" {
  type    = string
  default = "pilot"
}

variable "location" {
  type    = string
  default = "eastus"
}

variable "api_image_tag" {
  description = "Tag of discovery-api in the registry (a deploy pushes the commit SHA)."
  type        = string
}

variable "web_image_tag" {
  description = "Tag of discovery-web in the registry."
  type        = string
}

variable "allowed_cidrs" {
  description = "Addresses allowed to reach the demo, as CIDR ranges (for example 203.0.113.7/32). Required and non-empty: the pilot is access-limited, never public."
  type        = list(string)
  validation {
    condition     = length(var.allowed_cidrs) > 0 && alltrue([for c in var.allowed_cidrs : c != "0.0.0.0/0" && c != "::/0"])
    error_message = "allowed_cidrs must list at least one range and must not allow all addresses."
  }
}

variable "monthly_budget_usd" {
  description = "Budget alert threshold; the owner chose 25 for the Discovery pilot."
  type        = number
  default     = 25
}

variable "budget_emails" {
  type    = list(string)
  default = []
}
