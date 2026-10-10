# deploy/README.md

# Deployment

This directory contains Kubernetes manifests and Helm charts for the support
and standalone analytics products on EKS or AKS.

## Contents

-   **`helm/`**: Contains the Helm charts for our applications (API, Qdrant, Neo4j). Helm is used to package and manage the lifecycle of these applications.
-   **`ray/`**: Contains the Custom Resource Definitions (CRDs) for the Ray Cluster (`RayCluster`) and the AI model serving endpoints (`RayService`). These are managed by the KubeRay Operator.
-   **`ingress/`**: Contains the Ingress definitions for routing external traffic to our services, using Nginx or Kong.
-   **`secrets/`**: Configuration for the External Secrets Operator, which securely injects secrets from AWS Secrets Manager into our pods.
-   **`helm/analytics-api`** and **`helm/analytics-web`**: Separate analytics
    deployables used by the Azure analytics deployment script and workflow.

## Usage

The `scripts/bootstrap_cluster.sh` script handles the initial deployment of these components. For subsequent updates, you can use `helm` or `kubectl` commands.

```bash
# Example: Upgrade the API service
helm upgrade --install api deploy/helm/api

# Azure analytics product (after AKS, ACR, Key Vault, and ESO are ready)
ACR_NAME=<acr-name> ANALYTICS_HOSTNAME=analytics.example.com \
  ./scripts/deploy_azure_analytics.sh
```
