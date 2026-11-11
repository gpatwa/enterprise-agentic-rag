# ---- Entra identities (two per repository) ----------------------------------------------------------------------------

resource "azuread_application" "plan" {
  for_each         = local.targets
  display_name     = "${each.key}-infra-plan"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]
  notes            = "Read-only Terraform plan for ${each.value.repository} (GitHub OIDC). Managed by infra/terraform/platform-identity."
  lifecycle { ignore_changes = [owners] }
}

resource "azuread_service_principal" "plan" {
  for_each  = local.targets
  client_id = azuread_application.plan[each.key].client_id
  owners    = [data.azuread_client_config.current.object_id]
  lifecycle { ignore_changes = [owners] }
}

resource "azuread_application" "apply" {
  for_each         = local.targets
  display_name     = "${each.key}-infra-apply"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]
  notes            = "Terraform apply for ${each.value.repository} from protected environments on main (GitHub OIDC). Managed by infra/terraform/platform-identity."
  lifecycle { ignore_changes = [owners] }
}

resource "azuread_service_principal" "apply" {
  for_each  = local.targets
  client_id = azuread_application.apply[each.key].client_id
  owners    = [data.azuread_client_config.current.object_id]
  lifecycle { ignore_changes = [owners] }
}

# The subjects are exact (repository plus pull request, branch or environment): a workflow in any other repository, or in
# this one outside these contexts, cannot obtain a token for these identities. GitHub issues the IMMUTABLE form for these
# repositories (owner and repository IDs in the subject, `repo:owner@ownerId/name@repoId:...`, as reported by
# `gh api repos/OWNER/NAME/actions/oidc/customization/sub`), so a renamed or recreated repository cannot inherit the trust.
data "github_repository" "target" {
  for_each = local.targets
  name     = each.value.repository
}

locals {
  subject_prefix = {
    for k, t in local.targets : k => "repo:${var.github_owner}@${data.github_user.owner.id}/${t.repository}@${data.github_repository.target[k].repo_id}"
  }

  plan_subjects = merge([
    for k, t in local.targets : {
      "${k}-pr"   = { target = k, subject = "${local.subject_prefix[k]}:pull_request" }
      "${k}-main" = { target = k, subject = "${local.subject_prefix[k]}:ref:refs/heads/main" }
    }
  ]...)
  apply_subjects = merge([
    for k, t in local.targets : {
      for name, env in local.environments : "${k}-${name}" => {
        target  = k
        subject = "${local.subject_prefix[k]}:environment:${env}"
      }
    }
  ]...)
}

resource "azuread_application_federated_identity_credential" "plan" {
  for_each       = local.plan_subjects
  application_id = azuread_application.plan[each.value.target].id
  display_name   = "github-${each.key}"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = each.value.subject
}

resource "azuread_application_federated_identity_credential" "apply" {
  for_each       = local.apply_subjects
  application_id = azuread_application.apply[each.value.target].id
  display_name   = "github-${each.key}"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = each.value.subject
}

# ---- Microsoft Graph application permissions (admin consent) ----------------------------------------------------------
# plan:  read the directory (Terraform refreshes app registrations and users).
# apply: additionally change app registrations the identity OWNS. It cannot grant permissions to itself or others
#        (no AppRoleAssignment.ReadWrite.All): consent changes stay a local, owner-run step.

data "azuread_application_published_app_ids" "well_known" {}

data "azuread_service_principal" "msgraph" {
  client_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
}

locals {
  graph_assignments = merge(
    { for pair in setproduct(keys(local.targets), local.graph_roles.plan) : "plan-${pair[0]}-${pair[1]}" => { target = pair[0], kind = "plan", role = pair[1] } },
    { for pair in setproduct(keys(local.targets), local.graph_roles.apply) : "apply-${pair[0]}-${pair[1]}" => { target = pair[0], kind = "apply", role = pair[1] } },
  )
}

resource "azuread_app_role_assignment" "graph" {
  for_each            = local.graph_assignments
  app_role_id         = data.azuread_service_principal.msgraph.app_role_ids[each.value.role]
  principal_object_id = each.value.kind == "plan" ? azuread_service_principal.plan[each.value.target].object_id : azuread_service_principal.apply[each.value.target].object_id
  resource_object_id  = data.azuread_service_principal.msgraph.object_id
}

# ---- ownership of the existing app registrations -----------------------------------------------------------------------

locals {
  owned_apps = merge([
    for k, t in local.targets : { for name in t.owned_apps : "${k}-${name}" => { target = k, name = name } }
  ]...)
}

data "azuread_application" "owned" {
  for_each     = local.owned_apps
  display_name = each.value.name
}

resource "azuread_application_owner" "apply" {
  for_each        = local.owned_apps
  application_id  = data.azuread_application.owned[each.key].id
  owner_object_id = azuread_service_principal.apply[each.value.target].object_id
}
