#!/usr/bin/env bash
# Set the GitHub repository variables the Discovery workflows read, from `terraform output`.
# Idempotent: unchanged values are left alone, changed ones are updated, and a variable whose Terraform value is empty
# (for example the web sign-in settings while API auth is off) is removed. Uses the operator's own `gh` session; no
# token is stored anywhere. Everything set here is an identifier or a name, never a secret.
#
#   scripts/discovery_repo_vars.sh            apply
#   DRY_RUN=1 scripts/discovery_repo_vars.sh  print what would change and change nothing
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tf_dir="${TF_DIR:-$root/infra/terraform/azure-discovery-pilot}"
dry_run="${DRY_RUN:-0}"
terraform_bin="${TERRAFORM_BIN:-terraform}" # overridable so the logic can be tested with stubs
gh_bin="${GH_BIN:-gh}"

for tool in "$terraform_bin" "$gh_bin" jq; do
  command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 2; }
done
"$gh_bin" auth status >/dev/null 2>&1 || { echo "gh is not signed in: run 'gh auth login' first" >&2; exit 2; }

outputs="$("$terraform_bin" -chdir="$tf_dir" output -json)"
repo="$(jq -er '.github_repository.value' <<<"$outputs")" \
  || { echo "terraform output has no github_repository: apply the stack first" >&2; exit 2; }
vars="$(jq -er '.github_actions_variables.value' <<<"$outputs")" \
  || { echo "terraform output has no github_actions_variables: apply the stack first" >&2; exit 2; }

echo "Repository: $repo$([ "$dry_run" = 1 ] && echo '  (dry run: nothing will be changed)')"
changed=0
for name in $(jq -r 'keys[]' <<<"$vars"); do
  want="$(jq -r --arg k "$name" '.[$k] // ""' <<<"$vars")"
  have="$("$gh_bin" variable get "$name" -R "$repo" 2>/dev/null || true)"
  if [ -z "$want" ]; then
    if [ -n "$have" ]; then
      echo "  remove  $name"
      [ "$dry_run" = 1 ] || "$gh_bin" variable delete "$name" -R "$repo"
      changed=$((changed + 1))
    else
      echo "  ok      $name (unset)"
    fi
  elif [ "$have" = "$want" ]; then
    echo "  ok      $name"
  else
    echo "  $([ -n "$have" ] && echo update || echo set)  $name = $want"
    [ "$dry_run" = 1 ] || "$gh_bin" variable set "$name" -R "$repo" --body "$want"
    changed=$((changed + 1))
  fi
done

if [ "$changed" -eq 0 ]; then
  echo "Nothing to change."
elif [ "$dry_run" = 1 ]; then
  echo "$changed variable(s) would change. Run without DRY_RUN to apply."
else
  echo "$changed variable(s) changed."
fi
echo "Next: run the 'Discovery search VM' workflow (environment: discovery-pilot) to check the sign-in; if API auth was just enabled, run the Discovery deploy workflow so the web image is rebuilt with the new settings."
