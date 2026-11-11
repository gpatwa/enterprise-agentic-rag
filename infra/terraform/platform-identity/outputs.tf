output "plan_client_ids" {
  value = { for k in keys(local.targets) : k => azuread_application.plan[k].client_id }
}

output "apply_client_ids" {
  value = { for k in keys(local.targets) : k => azuread_application.apply[k].client_id }
}

output "repositories" {
  value = { for k, t in local.targets : k => "${var.github_owner}/${t.repository}" }
}
