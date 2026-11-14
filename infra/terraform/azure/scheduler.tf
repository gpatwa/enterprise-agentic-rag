# infra/terraform/azure/scheduler.tf
# Off-hours stop/start of the cluster and the database (.github/workflows/azure-schedule.yml). The identity that runs the
# schedule is the deploy identity created by scripts/set_github_secrets_azure.sh; it gets this role and nothing broader:
# it can read, start and stop the AKS cluster and the Postgres server, and cannot change, delete or read their contents.

resource "azurerm_role_definition" "cluster_scheduler" {
  name        = "${var.cluster_name}-scheduler"
  scope       = azurerm_resource_group.main.id
  description = "Start, stop and read the AKS cluster and the Postgres flexible server (scheduled off-hours stop)."

  permissions {
    actions = [
      "Microsoft.ContainerService/managedClusters/read",
      "Microsoft.ContainerService/managedClusters/start/action",
      "Microsoft.ContainerService/managedClusters/stop/action",
      "Microsoft.ContainerService/locations/operations/read",
      "Microsoft.ContainerService/locations/operationresults/read",
      "Microsoft.DBforPostgreSQL/flexibleServers/read",
      "Microsoft.DBforPostgreSQL/flexibleServers/start/action",
      "Microsoft.DBforPostgreSQL/flexibleServers/stop/action",
      "Microsoft.DBforPostgreSQL/locations/azureAsyncOperation/read",
      "Microsoft.DBforPostgreSQL/locations/operationResults/read",
      "Microsoft.Resources/subscriptions/resourceGroups/read",
    ]
    not_actions = []
  }

  assignable_scopes = [azurerm_resource_group.main.id]
}

output "scheduler_role_name" {
  description = "Role the schedule identity needs (assigned by scripts/set_github_secrets_azure.sh)"
  value       = azurerm_role_definition.cluster_scheduler.name
}
