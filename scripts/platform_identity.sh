#!/usr/bin/env bash
# Plan (default) or apply (APPLY=1) infra/terraform/platform-identity: the CI identities, their Azure and Graph permissions,
# the protected GitHub environments and the Actions variables for the product repositories.
#
# Uses the operator's own `az` and `gh` sessions and stores nothing. Safe to re-run; adding a repository is one entry in
# the stack's `local.targets`. This is the root of trust, so it is run by a person, never from CI.
#
# Environment:
#   APPLY=1             apply the plan that was just shown
#   TF_PLUGIN_DIR=...   use a local provider mirror (when the registry is slow or unreachable)
#   STATE_KEY_AUTH=1    first run only: read the state with the storage key until the operator's blob role exists
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
stack="$root/infra/terraform/platform-identity"

command -v terraform >/dev/null || { echo "terraform is required" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "run: gh auth login" >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "run: az login" >&2; exit 1; }

export GITHUB_TOKEN="$(gh auth token)"
init_args=(-input=false -reconfigure -backend-config=state.hcl)
if [ "${STATE_KEY_AUTH:-0}" = "1" ]; then
  ARM_ACCESS_KEY="$(az storage account keys list -g terraform-state-rg -n ragterraformstategp --query '[0].value' -o tsv)"
  export ARM_ACCESS_KEY
  init_args+=(-backend-config=use_azuread_auth=false)
fi
if [ -n "${TF_PLUGIN_DIR:-}" ]; then init_args+=("-plugin-dir=$TF_PLUGIN_DIR"); fi

cd "$stack"
terraform init "${init_args[@]}" >/dev/null
terraform validate
terraform plan -input=false -out=tfplan -no-color | sed -n '/Terraform will perform/,$p'
if [ "${APPLY:-0}" = "1" ]; then
  terraform apply -input=false tfplan
  rm -f tfplan
  echo "applied."
else
  rm -f tfplan
  echo "plan only. Re-run with APPLY=1 to apply."
fi
