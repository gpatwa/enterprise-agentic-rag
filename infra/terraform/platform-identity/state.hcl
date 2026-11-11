# Backend settings for this stack: none of it is secret (it names the storage account, not its key). Auth is Entra (the
# caller's `az login`, or OIDC in CI); no ARM_ACCESS_KEY is needed once the operator's blob role (rbac.tf) exists.
resource_group_name  = "terraform-state-rg"
storage_account_name = "ragterraformstategp"
container_name       = "tfstate"
key                  = "platform-identity/terraform.tfstate"
use_azuread_auth     = true
