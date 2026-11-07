# Access as code: the committed list in access.auto.tfvars (user principal names and a demo profile each) becomes
# app-role assignments on the sign-in app and the API's principal map. Nothing here is a secret.
#
# Granting or revoking access is a pull request that edits that file, then an apply. A user principal name that does
# not exist in the directory fails the plan with the name in the error (it never silently grants nothing).

locals {
  access_by_upn = { for a in var.access : lower(a.upn) => a }
}

# One lookup per person so a typo names the person. For a guest, the user principal name is the
# "name_domain#EXT#@tenant.onmicrosoft.com" form (az ad user show --id <email> --query userPrincipalName).
data "azuread_user" "access" {
  for_each            = local.access_by_upn
  user_principal_name = each.value.upn
}

locals {
  access_object_ids = { for upn, user in data.azuread_user.access : upn => user.object_id }

  # Everyone who is assigned the app: the access list plus any extra object IDs. Keyed by object ID so an ID that was
  # already assigned before the access list existed keeps its Terraform address (no destroy and recreate).
  signin_object_ids = toset(concat(var.allowed_user_object_ids, values(local.access_object_ids)))

  # DISCOVERY_ENTRA_PRINCIPAL_MAP: object id -> Discovery profile. A signed-in person who is not listed here still
  # authenticates but is mapped to their own object id, which has no profile, so they see nothing.
  principal_map = { for upn, a in local.access_by_upn : local.access_object_ids[upn] => a.principal_id }

  # DISCOVERY_ENTRA_TENANT_MAP: the one directory -> the Discovery tenant.
  tenant_map = { (data.azuread_client_config.current.tenant_id) = var.discovery_tenant_id }

  api_scope_value = "access_as_user"

  # Everything the API needs to validate version 2 access tokens for this app. Derived, never typed by hand.
  api_auth_env = var.enable_api_auth ? {
    DISCOVERY_AUTH_ENABLED         = "true"
    DISCOVERY_ENTRA_TENANT_ID      = data.azuread_client_config.current.tenant_id
    DISCOVERY_ENTRA_AUDIENCE       = azuread_application.web.client_id
    DISCOVERY_ENTRA_REQUIRED_SCOPE = local.api_scope_value
    DISCOVERY_ENTRA_TENANT_MAP     = jsonencode(local.tenant_map)
    DISCOVERY_ENTRA_PRINCIPAL_MAP  = jsonencode(local.principal_map)
  } : {}

  # The web build settings (VITE_ENTRA_*). Empty strings when API auth is off, so the web app then sends no token.
  web_build_env = var.enable_api_auth ? {
    DISCOVERY_ENTRA_CLIENT_ID = azuread_application.web.client_id
    DISCOVERY_ENTRA_TENANT_ID = data.azuread_client_config.current.tenant_id
    DISCOVERY_ENTRA_API_SCOPE = "api://${azuread_application.web.client_id}/${local.api_scope_value}"
    } : {
    DISCOVERY_ENTRA_CLIENT_ID = ""
    DISCOVERY_ENTRA_TENANT_ID = ""
    DISCOVERY_ENTRA_API_SCOPE = ""
  }
}
