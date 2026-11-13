#!/usr/bin/env bash
# scripts/deploy_ingestion_cluster_azure.sh
# Build the ingestion image in ACR (unless this commit's tag is already there) and apply the Ray cluster that runs it.
# Called by bootstrap_cluster_azure.sh; also runnable alone to roll out a new ingestion image without touching the rest.
set -euo pipefail

ACR_NAME="${ACR_NAME:-ragplatformacr}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "Deploying the ingestion Ray cluster..."
INGEST_ACR_URI="${ACR_NAME}.azurecr.io"
# Tag by the content the image runs, not by the commit: a change to a manifest, a job spec or a doc must not trigger a
# 10-minute rebuild, and a change to the ingestion code, the API app package it imports, its requirements or the
# Dockerfile must. Git tree and blob hashes are exact content hashes.
INGEST_TAG=$(git rev-parse HEAD:pipelines/ingestion HEAD:services/api/app HEAD:Dockerfile.ingestion \
    HEAD:requirements-ingestion.txt HEAD:.dockerignore 2>/dev/null | shasum -a 256 | cut -c1-12)
[ -n "$INGEST_TAG" ] || INGEST_TAG="v0.1.0"
if ! az acr repository show --name "$ACR_NAME" --image "rag-ingestion:${INGEST_TAG}" >/dev/null 2>&1; then
    echo "  Image rag-ingestion:${INGEST_TAG} not in ${ACR_NAME}; building it with az acr build (several minutes)..."
    # Build from a clean export of the commit, not the working directory: the directory can hold sockets (git's
    # fsmonitor daemon leaves .git/fsmonitor--daemon.ipc, which az acr build cannot tar), untracked files and local
    # edits, and the image must be what the tag says.
    INGEST_CTX="$(mktemp -d)"
    if git archive HEAD 2>/dev/null | tar -x -C "$INGEST_CTX"; then
        az acr build --registry "$ACR_NAME" --image "rag-ingestion:${INGEST_TAG}" --file Dockerfile.ingestion "$INGEST_CTX"
    else
        az acr build --registry "$ACR_NAME" --image "rag-ingestion:${INGEST_TAG}" --file Dockerfile.ingestion .
    fi
    rm -rf "${INGEST_CTX:?}"
else
    echo "  Image rag-ingestion:${INGEST_TAG} already in ${ACR_NAME}"
fi
# Workers start at 0 replicas; scripts/ingest_azure.sh scales them up for a run and back down.
sed "s#__INGESTION_IMAGE__#${INGEST_ACR_URI}/rag-ingestion:${INGEST_TAG}#g" deploy/ray/ray-cluster-azure.yaml | kubectl apply -f -


# KubeRay does not restart running pods for a changed image: recreate the head (and any worker) when the image moved.
current="$(kubectl get pods -l ray.io/cluster=rag-ray-cluster -o jsonpath='{.items[0].spec.containers[0].image}' 2>/dev/null || true)"
if [ -n "$current" ] && [ "$current" != "${INGEST_ACR_URI}/rag-ingestion:${INGEST_TAG}" ]; then
    echo "  Ray pods run $current; recreating them with the new image..."
    kubectl delete pods -l ray.io/cluster=rag-ray-cluster --wait=false
fi
