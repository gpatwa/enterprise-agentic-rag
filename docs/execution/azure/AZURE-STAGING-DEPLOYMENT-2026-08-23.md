# Azure Staging Deployment Evidence

Date: 2026-08-23  
Environment: `staging`  
Decision: **deployed for controlled demo validation; production approval not granted**

## Scope

This record captures the Azure staging deployment performed from the repository
using the existing Terraform, Helm, and landing-page deployment paths. It is
separate from the local-only LLM-057 readiness review. It does not certify
production readiness or replace the OpenSearch, TLS, backup, load, security, or
operations gates.

## Plan Used

- Terraform: `infra/terraform/azure/`
- Azure runbook: [`docs/deployment-azure.md`](../../deployment-azure.md)
- Cluster bootstrap: `scripts/bootstrap_cluster_azure.sh`
- Landing deployment: `scripts/deploy_azure_landing.sh`
- Terraform backend state key: `staging/terraform.tfstate`
- Subscription resource group: `rag-platform-rg`
- AKS cluster: `rag-platform-aks`

Terraform initialization, formatting, validation, planning, and apply completed.
The recovered apply completed with **1 resource added, 2 changed, and 0
destroyed**. The Redis resource was recreated after it was found absent from
the existing state, and the AKS cluster and analytics identity configuration
were reconciled.

## Application Evidence

| Check | Result |
|---|---|
| API image | ACR image tagged `e458407` |
| Helm release | `api`, revision 5, status `deployed` |
| API deployment rollout | Passed |
| Support worker rollout | Passed |
| Database migration | Passed; migration job cleaned up after success |
| API liveness | HTTP 200 through ingress IP |
| API readiness | HTTP 200; PostgreSQL, Redis, vector DB, and graph DB reported up |
| Public landing page | HTTP 200 at `https://red-pond-0fa9a940f.7.azurestaticapps.net` |

The API ingress currently routes `api.patwa-rag-platform.com` to the AKS load
balancer IP, but the hostname is not publicly resolvable until the Azure DNS
zone nameservers are delegated at the domain registrar.

## Deliberate Deployment Boundary

- The current Azure staging Helm values select **Qdrant** and **Neo4j** for the
  deployed fallback path.
- OpenSearch remains the target enterprise search plane, but the repository's
  OpenSearch Terraform module is provider-neutral and no live OpenSearch
  endpoint, credentials, index, or vector service was supplied for this run.
- TLS is not enabled on the current ingress; the verified API health path uses
  HTTP through the ingress IP. Public hostname TLS and certificate management
  remain pending.
- The landing site is publicly hosted, but this does not make the API a
  production service.

## Remaining Gates

1. Delegate `patwa-rag-platform.com` to the Azure DNS nameservers and verify
   public `api` resolution.
2. Configure ingress TLS, certificate renewal, secure headers, and redirect
   HTTP to HTTPS.
3. Provision and validate the live OpenSearch endpoint, BM25/vector/hybrid
   retrieval, ACL filtering, failure behavior, and observability.
4. Run production-like backup/restore, load, security, and operational drills.
5. Record named platform, security, and product sign-off before production
   traffic or external action execution.

No secrets or credential values are recorded in this document.
