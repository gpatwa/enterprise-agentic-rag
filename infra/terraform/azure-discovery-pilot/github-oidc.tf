# GitHub Actions signs in to Azure with OIDC (no client secret, no stored credential) to start, stop and read the
# search VM, and to do nothing else. The IDs the workflow needs are plain repository variables, set by
# `make discovery-repo-vars` from `terraform output`; see the README.

resource "azuread_application" "github_vm" {
  display_name     = "${local.name}-github-vm-operator"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]
}

resource "azuread_service_principal" "github_vm" {
  client_id = azuread_application.github_vm.client_id
  owners    = [data.azuread_client_config.current.object_id]
}

# One credential per allowed GitHub environment. The subject is exact (repository and environment): a workflow in
# another repository, or in this one but outside these environments, cannot obtain a token for this identity.
resource "azuread_application_federated_identity_credential" "github_vm" {
  for_each       = toset(var.github_environments)
  application_id = azuread_application.github_vm.id
  display_name   = "github-${each.value}"
  description    = "Search VM start/stop workflow in ${var.github_repository}, environment ${each.value}"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repository}:environment:${each.value}"
}

# Least privilege: a custom role that exists only on the search VM and allows exactly what the workflow runs
# (`az vm start`, `az vm deallocate`, `az vm get-instance-view`). No write, delete, run-command or anything else.
resource "azurerm_role_definition" "search_vm_operator" {
  name        = "${local.name}-search-vm-operator"
  scope       = azurerm_linux_virtual_machine.search.id
  description = "Start, deallocate and read the Discovery search VM. Nothing else."

  permissions {
    actions = [
      "Microsoft.Compute/virtualMachines/read",
      "Microsoft.Compute/virtualMachines/instanceView/read",
      "Microsoft.Compute/virtualMachines/start/action",
      "Microsoft.Compute/virtualMachines/deallocate/action",
    ]
    not_actions = []
  }

  assignable_scopes = [azurerm_linux_virtual_machine.search.id]
}

resource "azurerm_role_assignment" "github_vm_operator" {
  scope              = azurerm_linux_virtual_machine.search.id
  role_definition_id = azurerm_role_definition.search_vm_operator.role_definition_resource_id
  principal_id       = azuread_service_principal.github_vm.object_id
}
