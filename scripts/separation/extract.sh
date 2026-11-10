#!/usr/bin/env bash
# Extract one product into a new repository history with git filter-repo (see docs/REPO_SEPARATION_EXTRACTION_PLAN.md).
#
#   scripts/separation/extract.sh <analytics|discovery|support> <destination-dir> [source-repo]
#
# Works on a fresh clone of the source (never rewrites the source). Nothing is pushed. Requires git-filter-repo.
# Paths keep their location, so the Analytics release-manifest digests (computed from repository-relative paths) hold.
set -euo pipefail

product="${1:?product: analytics|discovery|support}"
dest="${2:?destination directory}"
src="${3:-$(git rev-parse --show-toplevel)}"

# Files every repository starts with (each gets its own README, CLAUDE.md and handoff afterwards).
common=(LICENSE .gitignore .dockerignore .pre-commit-config.yaml pyproject.toml Makefile README.md CLAUDE.md CONTRIBUTING.md
  .github/scripts .github/workflows/ci-gate.yml)

# Owned by Analytics (the landing site goes with it).
analytics_paths=(
  services/analytics-api apps/analytics-web apps/landing packages
  infra/terraform/azure-analytics-pilot scripts/analytics scripts/deploy_azure_analytics.sh scripts/deploy_azure_landing.sh
  docs/execution/enterprise-analytics docs/diagrams docs/compliance docs/operations docs/reviews docs/security
  docs/runbooks/analytics-operations.md
  docs/AGENTIC_DATA_STACK_EXECUTION_PLAN.md docs/ENTERPRISE_ANALYTICS_EXECUTION_PLAN.md
  docs/ANALYTICS_SNOWFLAKE_DATABRICKS_SCOPE.md docs/LANDING_MESSAGING_REVIEW.md
  docs/adr/ADR-ADS-001-agentic-data-stack-boundary.md docs/adr/ADR-ADS-002-graph-runtime.md
  docs/adr/ADR-ADS-008-apache-ossie-compatibility.md docs/adr/ADR-EA-002-cube-core-vs-internal-compiler.md
  docs/adr/ADR-EA-003-oidc-saml-scim.md docs/adr/ADS-008-ossie-compass-mapping.md
  .github/workflows/ci-analytics.yml .github/workflows/ci-analytics-web.yml .github/workflows/ci-landing.yml
  .github/workflows/ci-architecture.yml .github/workflows/ci-agentic-eval.yml .github/workflows/deploy-analytics-azure.yml
  .github/workflows/deploy-analytics-pilot-azure.yml .github/workflows/deploy-landing-azure.yml
)

# Owned by Discovery.
discovery_paths=(
  services/discovery-api apps/discovery-web infra/terraform/azure-discovery-pilot
  scripts/discovery_repo_vars.sh scripts/bootstrap_github_repo.sh infra/terraform/github-repo
  docs/execution/immersive-discovery docs/adr/ADR-IMD-001-immersive-discovery.md
  docs/adr/ADR-IMD-020-immersive-catalog-search.md docs/adr/ADR-IMD-042-cpu-ranker.md
  docs/adr/ADR-IMD-076-llm-context-engineering.md docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md
  docs/ZERO_MANUAL_SETUP_DESIGN.md docs/DISCOVERY_API_AUTH.md docs/DISCOVERY_BLOB_STORAGE.md
  docs/DISCOVERY_DEPLOYMENT_PROPOSAL.md docs/DISCOVERY_ESCI_SCOPE.md docs/DISCOVERY_INGESTION_RUNBOOK.md
  docs/DISCOVERY_PHASE2_COST_MODEL.md docs/DISCOVERY_PHASE2_REAL_DATA_SCOPE.md docs/DISCOVERY_PHASE2_SCOPE.md
  docs/DISCOVERY_SEARCH_VM_NETWORKING.md docs/DISCOVERY_STATUS.md
  .github/workflows/ci-discovery.yml .github/workflows/deploy-discovery-pilot-azure.yml
  .github/workflows/discovery-search-vm.yml
)

case "$product" in
analytics) mode=keep; paths=("${common[@]}" "${analytics_paths[@]}") ;;
discovery) mode=keep; paths=("${common[@]}" "${discovery_paths[@]}") ;;
support) mode=drop; paths=("${analytics_paths[@]}" "${discovery_paths[@]}") ;;
*) echo "unknown product: $product" >&2; exit 2 ;;
esac

rm -rf "$dest"
git clone --no-local --quiet "$src" "$dest"
cd "$dest"
args=()
for p in "${paths[@]}"; do args+=(--path "$p"); done
if [ "$mode" = drop ]; then args+=(--invert-paths); fi
git filter-repo --force "${args[@]}" >/dev/null 2>&1
echo "$product: $(git rev-list --count HEAD) commits, $(git ls-files | wc -l | tr -d ' ') files in $dest"
