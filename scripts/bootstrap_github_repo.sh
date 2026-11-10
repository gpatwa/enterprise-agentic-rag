#!/usr/bin/env bash
# Plan (default) or apply (APPLY=1) the repository settings stack in infra/terraform/github-repo.
# Uses the operator's own `gh` and `az` sessions; stores no token. Safe to re-run.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
stack="$root/infra/terraform/github-repo"
source_backend="$root/infra/terraform/azure-discovery-pilot/backend.hcl"
# Defaults are this repository; override to adopt a new one (see docs/REPO_SEPARATION_EXTRACTION_PLAN.md, X5):
#   REPO=gpatwa/agentic-data-analytics STATE_KEY=github-repo/agentic-data-analytics.tfstate PROTECTED_ENVS='[]' ...
repo="${REPO:-gpatwa/agentic-resolution-intelligence}"
state_key="${STATE_KEY:-github-repo/terraform.tfstate}"
protected_envs="${PROTECTED_ENVS:-[\"discovery-pilot\"]}"

command -v terraform >/dev/null || { echo "terraform is required" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "run: gh auth login" >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "run: az login" >&2; exit 1; }
[ -f "$source_backend" ] || { echo "missing $source_backend (the state storage settings live there)" >&2; exit 1; }

# Same state storage as the other stacks, its own state key.
sed "s|^key .*|key                  = \"$state_key\"|" "$source_backend" > "$stack/backend.hcl"

export GITHUB_TOKEN="$(gh auth token)"
cd "$stack"
terraform init -input=false -reconfigure -backend-config=backend.hcl >/dev/null

# Capture first: `grep -q` exiting early would otherwise SIGPIPE terraform and fail the pipeline under pipefail.
in_state() { local listed; listed="$(terraform state list 2>/dev/null || true)"; grep -qx "$1" <<<"$listed"; }

if ! in_state github_repository.this; then
  echo "importing the existing repository into state (no change to GitHub)"
  terraform import -input=false github_repository.this "${repo#*/}" >/dev/null
fi
if ! in_state github_repository_ruleset.default_branch; then
  id="$(gh api "repos/$repo/rulesets" --jq '.[] | select(.name=="main requires CI gate") | .id' | head -1)"
  if [ -n "$id" ]; then
    echo "importing existing ruleset $id"
    terraform import -input=false github_repository_ruleset.default_branch "${repo#*/}:$id" >/dev/null
  fi
fi

terraform plan -input=false -out=tfplan -no-color -var "repository=${repo#*/}" -var "owner=${repo%%/*}" -var "protected_environments=$protected_envs" | sed -n '/Terraform will perform/,$p'
if [ "${APPLY:-0}" = "1" ]; then
  terraform apply -input=false tfplan
  echo "applied. Verify with a throwaway PR (see README)."
else
  echo "plan only. Re-run with APPLY=1 to apply."
fi
