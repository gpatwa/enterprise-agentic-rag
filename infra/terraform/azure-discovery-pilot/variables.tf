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

variable "allowed_user_object_ids" {
  description = "Entra object IDs of the people who may sign in (for a guest, the object ID of their guest account in this tenant). Required and non-empty: the pilot is sign-in-only, never public."
  type        = list(string)
  validation {
    condition     = length(var.allowed_user_object_ids) > 0
    error_message = "allowed_user_object_ids must list at least one account."
  }
}

variable "allowed_cidrs" {
  description = "Optional second layer: when set, only these CIDR ranges can reach the web app, in addition to signing in. Empty (the default) means sign-in is the only gate."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for c in var.allowed_cidrs : c != "0.0.0.0/0" && c != "::/0"])
    error_message = "allowed_cidrs must not allow all addresses."
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
