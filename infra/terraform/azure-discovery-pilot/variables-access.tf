# Variables for the zero-manual setup (docs/ZERO_MANUAL_SETUP_DESIGN.md): access list, API auth, GitHub OIDC, Azure OpenAI.

# ---- access list (committed in access.auto.tfvars; names only, no secrets) ----
variable "access" {
  description = "Who may sign in and which demo profile each person sees. Terraform resolves each user principal name to an object ID, assigns the app role, and builds the API's principal map. Change this list by pull request."
  type = list(object({
    upn          = string
    principal_id = string
  }))
  default = []
  validation {
    condition     = length(distinct([for a in var.access : lower(a.upn)])) == length(var.access)
    error_message = "Each user principal name may appear once in access."
  }
  validation {
    condition     = alltrue([for a in var.access : can(regex("^[A-Za-z0-9._-]{1,64}$", a.principal_id))])
    error_message = "principal_id must be a Discovery profile id such as user-0001."
  }
}

variable "discovery_tenant_id" {
  description = "The Discovery tenant that the Entra directory maps to (DISCOVERY_ENTRA_TENANT_MAP). The demo catalog's web profile is tenant-01."
  type        = string
  default     = "tenant-01"
}

variable "enable_api_auth" {
  description = "When true the API requires an Entra bearer token and the web build gets the VITE_ENTRA_* settings. Leave false until the web image has been rebuilt with them (see README): turning it on first locks the web app out of the API."
  type        = bool
  default     = false
}

# ---- GitHub Actions OIDC for the search VM workflow ----
variable "github_repository" {
  description = "owner/name of the repository whose workflows may start and stop the search VM."
  type        = string
  default     = "gpatwa/enterprise-agentic-rag"
}

variable "github_environments" {
  description = "GitHub deployment environments allowed to sign in as the VM operator identity (one federated credential each). The workflow's environment input must be one of these."
  type        = list(string)
  default     = ["discovery-pilot"]
  validation {
    condition     = length(var.github_environments) > 0 && alltrue([for e in var.github_environments : can(regex("^[A-Za-z0-9._-]{1,64}$", e))])
    error_message = "List at least one environment name (letters, digits, dot, dash, underscore)."
  }
}

# ---- Discovery-owned Azure OpenAI ----
variable "enable_openai" {
  description = "Create the Discovery-owned Azure OpenAI account and its embedding deployment. Creating them makes no embedding call."
  type        = bool
  default     = true
}

variable "embedding_capacity" {
  description = "Capacity of the embedding deployment in thousands of tokens per minute (GlobalStandard). Small on purpose."
  type        = number
  default     = 10
}

variable "openai_user_object_ids" {
  description = "Entra object IDs of people who may call the embedding deployment from a laptop (az_cli auth). The API's managed identity always has the role."
  type        = list(string)
  default     = []
}
