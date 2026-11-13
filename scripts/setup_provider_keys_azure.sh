#!/usr/bin/env bash
# scripts/setup_provider_keys_azure.sh
# Onboarding for the two provider keys the platform cannot generate for itself: the Gemini key (embeddings, ingestion
# workers) and the OpenAI key (the LLM). One run collects them, proves they work, stores them in Key Vault, then applies
# them to the cluster. No file is edited and no value is written to disk or put on a command line.
#
# For each key, in order: the environment (GOOGLE_API_KEY / OPENAI_API_KEY), the copy already in Key Vault, then a hidden
# prompt when a terminal is attached. With none of those the script stops and says which key is missing.
#
# Then, per key: a live check against the provider (a read-only list call), and only a key that passes is stored (Key
# Vault secrets gemini-api-key and openai-api-key, the names the API reads at start). The stored value is read back and
# its length compared. Finally scripts/bootstrap_cluster_azure.sh refreshes the cluster secrets and the workloads are
# restarted so they pick the keys up.
#
# Terraform owns these two Key Vault secrets only when gemini_api_key / openai_api_key are set in terraform.tfvars.
# Leave those empty and use this script (the default), or set them there and do not run this script: not both.
#
# Environment:
#   GOOGLE_API_KEY, OPENAI_API_KEY   supply a key without a prompt (for CI-less, repeatable runs)
#   SKIP_CLUSTER=1                   store and verify the keys only; leave the cluster alone
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tf_dir="$root/infra/terraform/azure"

for tool in az curl terraform; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }
done
az account show >/dev/null 2>&1 || { echo "run: az login" >&2; exit 1; }

if [ ! -d "$tf_dir/.terraform" ]; then
  terraform -chdir="$tf_dir" init -input=false -backend-config="key=prod/terraform.tfstate" >/dev/null
fi
vault="$(terraform -chdir="$tf_dir" output -raw key_vault_name 2>/dev/null || true)"
[ -n "$vault" ] || { echo "terraform output key_vault_name is empty (is the Azure stack applied?)" >&2; exit 1; }

kv_get() { az keyvault secret show --vault-name "$vault" --name "$1" --query value -o tsv 2>/dev/null || true; }

# Read-only provider checks. The key travels on a curl config read from stdin, so it is not in the process list.
check_gemini() {
  printf 'header = "x-goog-api-key: %s"\n' "$1" |
    curl -s -o /dev/null -w '%{http_code}' -m 20 -K - "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
}
check_openai() {
  printf 'header = "Authorization: Bearer %s"\n' "$1" |
    curl -s -o /dev/null -w '%{http_code}' -m 20 -K - "https://api.openai.com/v1/models"
}

# ensure_key <label> <env var> <vault secret> <check function>
ensure_key() {
  local label="$1" env_name="$2" secret="$3" check="$4" value origin status stored
  value="${!env_name:-}"
  origin="environment"
  if [ -z "$value" ]; then
    value="$(kv_get "$secret")"
    origin="Key Vault"
  fi
  if [ -z "$value" ] && [ -t 0 ]; then
    read -r -s -p "${label} API key (input hidden): " value
    echo
    origin="prompt"
  fi
  if [ -z "$value" ]; then
    echo "No ${label} key: set ${env_name}, or run this script in a terminal to be asked." >&2
    exit 1
  fi

  status="$("$check" "$value" || true)"
  if [ "$status" != "200" ]; then
    echo "${label} key (from ${origin}) was rejected by the provider (HTTP ${status:-none}); nothing stored." >&2
    exit 1
  fi
  echo "${label}: key from ${origin} accepted by the provider."

  stored="$(kv_get "$secret")"
  if [ "$stored" = "$value" ]; then
    echo "${label}: already in Key Vault (${secret})."
    return
  fi
  printf %s "$value" | az keyvault secret set --vault-name "$vault" --name "$secret" --file /dev/stdin \
    --encoding utf-8 >/dev/null
  stored="$(kv_get "$secret")"
  if [ "${#stored}" != "${#value}" ]; then
    echo "${label}: Key Vault copy has length ${#stored}, expected ${#value}; check the vault." >&2
    exit 1
  fi
  echo "${label}: stored in Key Vault (${secret}) and read back."
}

ensure_key "Gemini" GOOGLE_API_KEY gemini-api-key check_gemini
ensure_key "OpenAI" OPENAI_API_KEY openai-api-key check_openai

if [ "${SKIP_CLUSTER:-0}" = "1" ]; then
  echo "SKIP_CLUSTER=1: keys are in Key Vault; run scripts/bootstrap_cluster_azure.sh to apply them."
  exit 0
fi

# The bootstrap reads the Gemini key from Key Vault into the cluster secrets (app-env-secret, ray-gemini-api-key).
"$root/scripts/bootstrap_cluster_azure.sh"

# Pods read the keys at start, so restart the ones that use them.
for deployment in api-deployment api-support-worker; do
  if kubectl get deployment "$deployment" >/dev/null 2>&1; then
    kubectl rollout restart "deployment/$deployment"
    kubectl rollout status "deployment/$deployment" --timeout=300s
  fi
done
echo "provider keys are set up."
