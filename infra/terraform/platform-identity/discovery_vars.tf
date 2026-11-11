# The Discovery stack declares, as an output, every identifier its GitHub workflows need (the VM operator's client ID, names,
# and the web sign-in settings once API auth is on). This reads that output and keeps the repository variables in step with
# it, so nobody has to remember to run scripts/discovery_repo_vars.sh. All values are identifiers or names, never secrets.
#
# Re-run scripts/platform_identity.sh after the Discovery stack's outputs change (it is idempotent). An empty value removes
# the variable, as the old script did.
data "terraform_remote_state" "discovery" {
  backend = "azurerm"
  config = {
    resource_group_name  = var.state_resource_group
    storage_account_name = var.state_storage_account
    container_name       = var.state_container
    key                  = local.targets.discovery.state_key
    use_azuread_auth     = true
  }
}

locals {
  discovery_stack_variables = {
    for name, value in try(data.terraform_remote_state.discovery.outputs.github_actions_variables, {}) :
    name => value if value != null && value != ""
  }
}

resource "github_actions_variable" "discovery_stack" {
  for_each      = local.discovery_stack_variables
  repository    = local.targets.discovery.repository
  variable_name = each.key
  value         = each.value
}
