#!/usr/bin/env bash
# Build and publish the public Compass landing page to Azure Static Web Apps.
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rag-platform-rg}"
STATIC_WEB_APP_NAME="${STATIC_WEB_APP_NAME:-compass-landing}"
SITE_URL="${SITE_URL:-}"

command -v az >/dev/null || { echo "Missing required command: az" >&2; exit 1; }
command -v npx >/dev/null || { echo "Missing required command: npx" >&2; exit 1; }
az account show >/dev/null || { echo "Run az login first" >&2; exit 1; }

if [[ -z "$SITE_URL" ]]; then
  SITE_URL="https://$(az staticwebapp show --name "$STATIC_WEB_APP_NAME" --resource-group "$RESOURCE_GROUP" --query defaultHostname -o tsv)"
fi

echo "Building landing page with canonical URL: $SITE_URL"
(
  cd apps/support-web
  VITE_SITE_URL="$SITE_URL" npm ci --no-audit --no-fund
  VITE_SITE_URL="$SITE_URL" npm run build
  DEPLOY_TOKEN="$(az staticwebapp secrets list --name "$STATIC_WEB_APP_NAME" --resource-group "$RESOURCE_GROUP" --query properties.apiKey -o tsv)"
  test -n "$DEPLOY_TOKEN"
  npx --yes @azure/static-web-apps-cli@2.0.10 deploy dist --deployment-token "$DEPLOY_TOKEN" --env production
)

echo "Landing deployed: $SITE_URL"
