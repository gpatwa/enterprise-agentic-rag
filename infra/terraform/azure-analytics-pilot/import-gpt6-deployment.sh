#!/usr/bin/env bash
# Imports the hand-made gpt-6-luna deployment into this stack's state. Idempotent: does nothing when the resource is
# already in state. Run it from this directory after `terraform init -backend-config=backend.hcl`, with the same
# terraform.tfvars / secrets.auto.tfvars you use for `terraform plan` (Terraform needs the variables to import).
#
#   ./import-gpt6-deployment.sh --dry-run   # print what would run, change nothing
#   ./import-gpt6-deployment.sh             # import
#
# Then run `terraform plan`: expect no change to the deployment. Only the owner of the stack should run the import.
set -euo pipefail
cd "$(dirname "$0")"

ACCOUNT="${OPENAI_ACCOUNT:-compass-pilot-openai}"
RESOURCE_GROUP="${OPENAI_RESOURCE_GROUP:-compass-pilot-rg}"
DEPLOYMENT="${GPT6_DEPLOYMENT:-gpt-6-luna}"
ADDRESS='azurerm_cognitive_deployment.intent_gpt6[0]'
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

SUBSCRIPTION="${ARM_SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"
# azurerm ~> 3.117 import ID: the ARM ID of the deployment under its account.
ID="/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${ACCOUNT}/deployments/${DEPLOYMENT}"

if terraform state list 2>/dev/null | grep -Fxq "${ADDRESS}"; then
  echo "already in state: ${ADDRESS}; nothing to do"
  exit 0
fi

# Read-only check that the deployment exists, so a typo does not fail halfway through an import.
az cognitiveservices account deployment show -g "${RESOURCE_GROUP}" -n "${ACCOUNT}" --deployment-name "${DEPLOYMENT}" \
  --query name -o tsv >/dev/null

echo "terraform import '${ADDRESS}' '${ID}'"
if [[ "${DRY_RUN}" == "true" ]]; then
  echo "dry run: not importing"
  exit 0
fi
terraform import "${ADDRESS}" "${ID}"
