#!/usr/bin/env bash
# Deploy the standalone Compass Analytics product to an existing Azure AKS
# cluster. Terraform/bootstrap remain explicit separate operations.
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rag-platform-rg}"
CLUSTER_NAME="${CLUSTER_NAME:-rag-platform-aks}"
ACR_NAME="${ACR_NAME:-}"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
NAMESPACE="${NAMESPACE:-default}"
ANALYTICS_HOSTNAME="${ANALYTICS_HOSTNAME:-analytics.example.com}"
ANALYTICS_API_IDENTITY_CLIENT_ID="${ANALYTICS_API_IDENTITY_CLIENT_ID:-}"

if [[ -z "$ACR_NAME" ]]; then
  echo "ACR_NAME is required (for example: ragplatformacr)" >&2
  exit 1
fi
for command_name in az docker helm kubectl; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 1; }
done
az account show >/dev/null || { echo "Run az login first" >&2; exit 1; }

ACR_URI="${ACR_NAME}.azurecr.io"
az acr login --name "$ACR_NAME"

echo "Building analytics API and web images for linux/amd64"
docker build --platform linux/amd64 -t "$ACR_URI/compass-analytics-api:$TAG" -f services/analytics-api/Dockerfile .
docker build --platform linux/amd64 -t "$ACR_URI/compass-analytics-web:$TAG" -f apps/analytics-web/Dockerfile apps/analytics-web
docker push "$ACR_URI/compass-analytics-api:$TAG"
docker push "$ACR_URI/compass-analytics-web:$TAG"

az aks get-credentials --resource-group "$RESOURCE_GROUP" --name "$CLUSTER_NAME" --overwrite-existing

api_set=(
  --set-string "image.repository=$ACR_URI/compass-analytics-api"
  --set-string "image.tag=$TAG"
  --set-string "secretRef=analytics-api-secrets"
)
if [[ -n "$ANALYTICS_API_IDENTITY_CLIENT_ID" ]]; then
  api_set+=(--set-string 'serviceAccount.annotations.azure\.workload\.identity/client-id='"$ANALYTICS_API_IDENTITY_CLIENT_ID")
fi

helm upgrade --install analytics-api deploy/helm/analytics-api \
  --namespace "$NAMESPACE" --create-namespace \
  -f deploy/helm/analytics-api/values-azure.yaml "${api_set[@]}" \
  --wait --timeout 300s

helm upgrade --install analytics-web deploy/helm/analytics-web \
  --namespace "$NAMESPACE" \
  -f deploy/helm/analytics-web/values-azure.yaml \
  --set-string "image.repository=$ACR_URI/compass-analytics-web" \
  --set-string "image.tag=$TAG" \
  --set-string "apiHost=analytics-api:8090" \
  --set ingress.enabled=true \
  --set-string "ingress.host=$ANALYTICS_HOSTNAME" \
  --wait --timeout 300s

kubectl rollout status deployment/analytics-api --namespace "$NAMESPACE" --timeout=180s
kubectl rollout status deployment/analytics-web --namespace "$NAMESPACE" --timeout=180s
kubectl get ingress analytics-web --namespace "$NAMESPACE"
