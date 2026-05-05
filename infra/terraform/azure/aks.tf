# infra/terraform/azure/aks.tf
# Azure Kubernetes Service — equivalent to AWS EKS.
# Uses system + app node pools (like EKS managed node groups).
# Cluster Autoscaler is built into AKS (no Karpenter needed).

resource "azurerm_kubernetes_cluster" "aks" {
  name                = var.cluster_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  dns_prefix          = var.cluster_name
  # 1.32 became LTS-only (Premium tier). Default non-LTS in eastus is
  # 1.34 (`az aks get-versions -l eastus`). Bump in lock-step with that.
  kubernetes_version = "1.34"

  # System node pool — runs CoreDNS, metrics-server, etc.
  default_node_pool {
    name                 = "system"
    vm_size              = "Standard_B2s" # Burstable 2 vCPU, 4 GB — similar to t3a.medium
    node_count           = 1
    min_count            = 1
    max_count            = 2
    enable_auto_scaling = true
    os_disk_size_gb      = 30
    vnet_subnet_id       = azurerm_subnet.aks.id

    # Note: AKS API no longer allows custom taints on the default node pool.
    # Use the app node pool for workloads and keep system pool for cluster addons.

    node_labels = {
      "nodepool" = "system"
    }
  }

  # Managed Identity (replaces AWS IRSA with Azure Workload Identity)
  identity {
    type = "SystemAssigned"
  }

  # Enable OIDC issuer for Workload Identity (equivalent to EKS IRSA)
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  # Networking: Azure CNI for pod-level VNet integration
  network_profile {
    network_plugin    = "azure"
    network_policy    = "calico"
    load_balancer_sku = "standard"
    service_cidr      = "172.16.0.0/16"  # Must not overlap with vnet_cidr
    dns_service_ip    = "172.16.0.10"
  }

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# App node pool — runs API, Qdrant, Neo4j pods (like EKS app node group)
resource "azurerm_kubernetes_cluster_node_pool" "app" {
  name                  = "app"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.aks.id
  vm_size               = "Standard_B2s_v2" # Dev: burstable v2 (prod: Standard_D4s_v5+)
  node_count            = 1
  min_count             = 1
  max_count             = 3
  enable_auto_scaling   = true
  os_disk_size_gb       = 30
  vnet_subnet_id        = azurerm_subnet.aks.id
  priority              = "Regular" # Regular VMs (Spot has capacity issues in eastus)

  node_labels = {
    "nodepool" = "app"
  }

  tags = {
    Project     = "Enterprise-RAG"
    Environment = var.environment
  }
}

# Assign AcrPull role so AKS can pull images from ACR
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id
}
