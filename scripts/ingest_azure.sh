#!/usr/bin/env bash
# scripts/ingest_azure.sh <file-or-directory> [tenant-id]
# Ingest local documents into the Azure deployment, end to end, with no manual steps:
#   1. upload them to the documents container (your az login; falls back to the storage key from your own session)
#   2. scale the Ray ingestion workers up
#   3. submit the ingestion job (pipelines/ingestion/main.py) to the Ray head with the env from pipelines/jobs/ray_job.yaml
#   4. wait for it, print the log tail and what landed in Qdrant and Neo4j
#   5. scale the workers back to zero (always, even when the job fails)
#
# The pods authenticate to Blob, Azure OpenAI and the databases with their own identity or in-cluster settings; nothing
# here handles a provider key. Needs: az (logged in), kubectl pointed at the cluster, python3 with PyYAML.
#
# Environment:
#   TENANT_ID        tenant the chunks are written under (default: the second argument, else "default")
#   INGEST_*         any such variable overrides the job file for this run (INGEST_GRAPH_PROVIDER=none: vectors only)
#   KEEP_WORKERS=1   leave the workers running afterwards
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
source_path="${1:?usage: ingest_azure.sh <file-or-directory> [tenant-id]}"
tenant="${2:-${TENANT_ID:-default}}"
[ -e "$source_path" ] || { echo "no such file or directory: $source_path" >&2; exit 1; }
for tool in az kubectl python3; do command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }; done

cluster="${RAY_CLUSTER:-rag-ray-cluster}"
tf_dir="$root/infra/terraform/azure"
account="$(terraform -chdir="$tf_dir" output -raw storage_account_name)"
container="$(terraform -chdir="$tf_dir" output -raw storage_container_name)"
run_id="ingest-$(date +%Y%m%d-%H%M%S)"
# A document's identity in the index is its blob path, so the path must not change between runs: re-ingesting the same
# file then updates its chunks in place instead of adding a second copy under a new folder.
name="$(basename "$source_path")"
if [ -d "$source_path" ]; then prefix="uploads/${tenant}/${name}/"; else prefix="uploads/${tenant}/${name}"; fi

scale_workers() {  # scale_workers <replicas>
  kubectl patch raycluster "$cluster" --type json \
    -p "[{\"op\":\"replace\",\"path\":\"/spec/workerGroupSpecs/0/replicas\",\"value\":$1}]" >/dev/null
}
cleanup() {
  if [ "${KEEP_WORKERS:-0}" != "1" ]; then
    echo "Scaling Ray workers to 0..."
    scale_workers 0 || true
  fi
}
trap cleanup EXIT

# --- 1. upload --------------------------------------------------------------------------------------------------------
echo "Uploading to az://${container}/${prefix} ..."
upload() {
  if [ -d "$source_path" ]; then
    az storage blob upload-batch --account-name "$account" --destination "$container" --destination-path "${prefix%/}" \
      --source "$source_path" "$@" >/dev/null
  else
    az storage blob upload --account-name "$account" --container-name "$container" \
      --name "$prefix" --file "$source_path" --overwrite "$@" >/dev/null
  fi
}
if ! upload --auth-mode login 2>/dev/null; then
  echo "  (no Blob data role for your login; using the storage key from your own session, kept in this process only)"
  AZURE_STORAGE_KEY="$(az storage account keys list --account-name "$account" --query '[0].value' -o tsv)"
  export AZURE_STORAGE_KEY
  upload
  unset AZURE_STORAGE_KEY
fi

# --- 2. workers --------------------------------------------------------------------------------------------------------
echo "Scaling Ray workers to 1..."
scale_workers 1
head="$(kubectl get pods -l ray.io/cluster="$cluster",ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')"
kubectl wait --for=condition=Ready "pod/$head" --timeout=900s
for _ in $(seq 1 90); do
  ready="$(kubectl get pods -l ray.io/cluster="$cluster",ray.io/group=cpu-workers --no-headers 2>/dev/null | grep -c ' 1/1 ' || true)"
  [ "$ready" -ge 1 ] && break
  sleep 10
done
[ "${ready:-0}" -ge 1 ] || { echo "no Ray worker became Ready" >&2; kubectl get pods -l ray.io/cluster="$cluster"; exit 1; }

# --- 3. submit ---------------------------------------------------------------------------------------------------------
runtime_env="$(python3 - "$root/pipelines/jobs/ray_job.yaml" "$tenant" <<'PY'
import json, sys, yaml
spec = yaml.safe_load(open(sys.argv[1]))
env = dict(spec["runtime_env"]["env_vars"])
env["TENANT_ID"] = sys.argv[2]
# Any INGEST_* variable set when running this script overrides the job file (e.g. INGEST_GRAPH_PROVIDER=none for a
# vector-only run, INGEST_GRAPH_CONCURRENCY=4 for more parallel graph calls).
import os
env.update({k: v for k, v in os.environ.items() if k.startswith("INGEST_")})
print(json.dumps({"env_vars": env}))
PY
)"
echo "Submitting ${run_id} ..."
kubectl exec "$head" -- ray job submit --address http://127.0.0.1:8265 --submission-id "$run_id" --no-wait \
  --runtime-env-json "$runtime_env" -- python /app/pipelines/ingestion/main.py "$container" "$prefix" >/dev/null

status=""
for _ in $(seq 1 360); do
  status="$(kubectl exec "$head" -- ray job status --address http://127.0.0.1:8265 "$run_id" 2>/dev/null \
    | grep -o -i -E "succeeded|failed|stopped" | head -1 | tr '[:lower:]' '[:upper:]' || true)"
  [ -n "$status" ] && break
  sleep 10
done

# --- 4. result ---------------------------------------------------------------------------------------------------------
echo "---- job log (tail) ----"
kubectl exec "$head" -- ray job logs --address http://127.0.0.1:8265 "$run_id" 2>/dev/null | tail -25 || true
echo "---- result: ${status:-TIMED_OUT} ----"
if [ "$status" = "SUCCEEDED" ]; then
  kubectl exec -i "$head" -- python - "$tenant" <<'PY' || true
import os, sys
from qdrant_client import QdrantClient
from qdrant_client.http import models
tenant = sys.argv[1]
q = QdrantClient(host=os.environ["QDRANT_HOST"], port=int(os.environ["QDRANT_PORT"]))
name = os.environ.get("QDRANT_COLLECTION", "rag_collection")
n = q.count(name, count_filter=models.Filter(must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant))]), exact=True).count
print(f"Qdrant: {n} points in '{name}' for tenant '{tenant}'")
PY
  exit 0
fi
exit 1
