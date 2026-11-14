#!/usr/bin/env bash
# scripts/set_github_secrets_azure.sh
# Gives the `production` GitHub environment everything .github/workflows/deploy-prod.yml (Azure job) reads, taken from
# what already exists: the Terraform outputs of infra/terraform/azure, the operator's `az` session, and a deploy identity
# this script finds or creates.
#
# Plan by default (prints the names and where each value comes from, writes nothing). APPLY=1 creates the deploy
# identity and sets the secrets. It uses the operator's own `az` and `gh` logins and stores nothing; run it by hand, never
# from CI. Safe to re-run.
#
# What it sets (environment secrets on the `production` environment, so only that environment's jobs can read them):
#   AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID   from `az account show`
#   AZURE_CLIENT_ID                          the deploy identity (Entra app + service principal, GitHub OIDC)
#   ACR_NAME, AZURE_RESOURCE_GROUP, AKS_CLUSTER_NAME, API_IDENTITY_CLIENT_ID   from `terraform output`
#
# What it creates with APPLY=1 (only if missing):
#   - Entra app "<repo>-deploy" with a federated credential for repo:<owner>@<id>/<repo>@<id>:environment:production
#     (no client secret exists; GitHub exchanges its OIDC token)
#   - AcrPush on the registry and "Azure Kubernetes Service Cluster User Role" on the cluster, plus (once the Terraform has
#     created it) the narrow "<cluster>-scheduler" role that lets the off-hours schedule start and stop the cluster and the
#     database; nothing broader
#
# What it does not touch: the `production` environment itself (its approval rules stay as they are; it must already exist).
#
# Environment:
#   APPLY=1           create the identity and set the secrets
#   REPO=owner/name   default: the repository of the current checkout
#   GH_ENVIRONMENT    default: production
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tf_dir="$root/infra/terraform/azure"
apply="${APPLY:-0}"
environment="${GH_ENVIRONMENT:-production}"

for tool in az gh terraform; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }
done
gh auth status >/dev/null 2>&1 || { echo "run: gh auth login" >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "run: az login" >&2; exit 1; }

repo="${REPO:-$(cd "$root" && gh repo view --json nameWithOwner -q .nameWithOwner)}"
repo_name="${repo#*/}"
app_name="${repo_name}-deploy"

# The environment must exist: its protection rules are the owner's and are not created or changed here.
if ! gh api "repos/${repo}/environments/${environment}" >/dev/null 2>&1; then
  echo "GitHub environment '${environment}' does not exist in ${repo}; create it (with its approval rules) first." >&2
  exit 1
fi

# --- values that come from Terraform and the current az session ---------------------------------------------------------
tf_output() { terraform -chdir="$tf_dir" output -raw "$1" 2>/dev/null || true; }

if [ ! -d "$tf_dir/.terraform" ]; then
  terraform -chdir="$tf_dir" init -input=false -backend-config="key=prod/terraform.tfstate" >/dev/null
fi

tenant_id="$(az account show --query tenantId -o tsv)"
subscription_id="$(az account show --query id -o tsv)"
acr_name="$(tf_output acr_name)"
aks_name="$(tf_output aks_cluster_name)"
resource_group="$(tf_output resource_group_name)"
api_identity_client_id="$(tf_output api_identity_client_id)"

missing=()
for pair in "acr_name:$acr_name" "aks_cluster_name:$aks_name" "resource_group_name:$resource_group" \
            "api_identity_client_id:$api_identity_client_id"; do
  [ -n "${pair#*:}" ] || missing+=("${pair%%:*}")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "terraform output is empty for: ${missing[*]} (is the Azure stack applied and the prod state key initialised?)" >&2
  exit 1
fi

acr_id="$(az acr show --name "$acr_name" --query id -o tsv)"
aks_id="$(az aks show --resource-group "$resource_group" --name "$aks_name" --query id -o tsv)"

# --- the deploy identity -------------------------------------------------------------------------------------------------
client_id="$(az ad app list --display-name "$app_name" --query '[0].appId' -o tsv 2>/dev/null || true)"

echo "Repository:        ${repo}"
echo "Environment:       ${environment}"
echo "Deploy identity:   ${app_name} ($([ -n "$client_id" ] && echo "exists" || echo "will be created"))"
echo "Registry:          ${acr_name}   Cluster: ${aks_name}   Resource group: ${resource_group}"
echo "Secrets to set:    AZURE_TENANT_ID AZURE_SUBSCRIPTION_ID AZURE_CLIENT_ID ACR_NAME AZURE_RESOURCE_GROUP" \
     "AKS_CLUSTER_NAME API_IDENTITY_CLIENT_ID"

if [ "$apply" != "1" ]; then
  echo "plan only. Re-run with APPLY=1 to create the identity and set the secrets."
  exit 0
fi

if [ -z "$client_id" ]; then
  client_id="$(az ad app create --display-name "$app_name" --query appId -o tsv)"
  az ad sp create --id "$client_id" >/dev/null
  echo "created Entra app ${app_name}"
fi

# GitHub presents the immutable-ID form of the subject (owner and repository IDs, as infra/terraform/platform-identity
# registers them); the plain repo:<owner>/<name> form never matches.
read -r owner_id repo_id < <(gh api "repos/${repo}" --jq '"\(.owner.id) \(.id)"')
subject="repo:${repo%%/*}@${owner_id}/${repo_name}@${repo_id}:environment:${environment}"
existing_subjects="$(az ad app federated-credential list --id "$client_id" --query '[].subject' -o tsv)"
if ! grep -qxF "$subject" <<<"$existing_subjects"; then
  credential="$(printf '{"name":"github-%s","issuer":"https://token.actions.githubusercontent.com","subject":"%s","audiences":["api://AzureADTokenExchange"]}' \
    "$environment" "$subject")"
  # A credential of this name with another subject (for example the plain repo form) is corrected, not duplicated.
  stale_id="$(az ad app federated-credential list --id "$client_id" --query "[?name=='github-${environment}'].id" -o tsv)"
  if [ -n "$stale_id" ]; then
    az ad app federated-credential update --id "$client_id" --federated-credential-id "$stale_id" --parameters "$credential" >/dev/null
    echo "updated federated credential to ${subject}"
  else
    az ad app federated-credential create --id "$client_id" --parameters "$credential" >/dev/null
    echo "added federated credential for ${subject}"
  fi
fi

assign_role() {  # assign_role <role> <scope>
  local existing
  existing="$(az role assignment list --assignee "$client_id" --role "$1" --scope "$2" --query '[0].id' -o tsv)"
  if [ -z "$existing" ]; then
    az role assignment create --assignee "$client_id" --role "$1" --scope "$2" >/dev/null
    echo "granted $1"
  fi
}
assign_role "AcrPush" "$acr_id"
assign_role "Azure Kubernetes Service Cluster User Role" "$aks_id"

# The off-hours schedule (.github/workflows/azure-schedule.yml) stops and starts the cluster and the database with this
# identity. The role is defined in infra/terraform/azure/scheduler.tf and can only read, start and stop those two resources.
scheduler_role="${aks_name}-scheduler"
if [ -n "$(az role definition list --name "$scheduler_role" --query '[0].name' -o tsv 2>/dev/null)" ]; then
  assign_role "$scheduler_role" "$(az group show --name "$resource_group" --query id -o tsv)"
else
  echo "role '${scheduler_role}' does not exist yet: apply infra/terraform/azure, then re-run this script to enable the off-hours schedule"
fi

# --- the secrets: values go in on stdin, never on a command line -------------------------------------------------------
set_secret() {  # set_secret <NAME> <value>
  printf %s "$2" | gh secret set "$1" --repo "$repo" --env "$environment"
}
set_secret AZURE_TENANT_ID "$tenant_id"
set_secret AZURE_SUBSCRIPTION_ID "$subscription_id"
set_secret AZURE_CLIENT_ID "$client_id"
set_secret ACR_NAME "$acr_name"
set_secret AZURE_RESOURCE_GROUP "$resource_group"
set_secret AKS_CLUSTER_NAME "$aks_name"
set_secret API_IDENTITY_CLIENT_ID "$api_identity_client_id"
echo "set 7 secrets on ${repo} environment '${environment}'."
echo "Run the workflow: gh workflow run deploy-prod.yml --repo ${repo} -f cloud=azure"
