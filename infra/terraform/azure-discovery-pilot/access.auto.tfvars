# Who may sign in to the Discovery pilot, and which demo profile each person sees. Names only: no secrets, no object IDs.
# Terraform looks each user principal name up in the directory, assigns the sign-in app role, and generates the API's
# DISCOVERY_ENTRA_PRINCIPAL_MAP. To grant or revoke access, change this list in a pull request and apply.
#
# upn          the user principal name: az ad user show --id <email> --query userPrincipalName -o tsv
#              (a guest's looks like name_domain.com#EXT#@<tenant>.onmicrosoft.com)
# principal_id the demo profile the person sees, for example user-0001 (the catalog has user-0001 and up)
access = [
  {
    upn          = "govindpatwa_hotmail.com#EXT#@govindpatwahotmail.onmicrosoft.com"
    principal_id = "user-0001"
  },
]
