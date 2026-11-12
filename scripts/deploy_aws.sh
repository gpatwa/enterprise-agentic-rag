#!/bin/bash
# scripts/deploy_aws.sh
# Full AWS deployment orchestrator: Terraform -> ECR -> EKS -> Verify
# Usage: ./scripts/deploy_aws.sh [--skip-infra] [--skip-build] [--skip-bootstrap]
#
# For first-time deploy, run without flags.
# For subsequent deploys (code changes only): ./scripts/deploy_aws.sh --skip-infra

set -euo pipefail

CLUSTER_NAME="rag-platform-cluster"
REGION="us-east-1"
REPO_NAME="rag-backend-api"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Parse flags
SKIP_INFRA=false
SKIP_BUILD=false
SKIP_BOOTSTRAP=false

for arg in "$@"; do
    case $arg in
        --skip-infra) SKIP_INFRA=true ;;
        --skip-build) SKIP_BUILD=true ;;
        --skip-bootstrap) SKIP_BOOTSTRAP=true ;;
    esac
done

echo "========================================"
echo "  RAG Pipeline — AWS Deployment"
echo "========================================"
echo "  Cluster:  $CLUSTER_NAME"
echo "  Region:   $REGION"
echo "  Flags:    infra=$([ "$SKIP_INFRA" = true ] && echo 'skip' || echo 'apply')" \
     "build=$([ "$SKIP_BUILD" = true ] && echo 'skip' || echo 'run')" \
     "bootstrap=$([ "$SKIP_BOOTSTRAP" = true ] && echo 'skip' || echo 'run')"
echo "========================================"
echo ""

# -----------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------
echo "Pre-flight checks..."

# AWS CLI
if ! aws sts get-caller-identity &>/dev/null; then
    echo "ERROR: AWS CLI not configured. Run: aws configure --profile rag-prod"
    exit 1
fi
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
echo "  AWS Account: $ACCOUNT_ID"

# Terraform
if ! command -v terraform &>/dev/null; then
    echo "ERROR: terraform not found. Install: https://developer.hashicorp.com/terraform/install"
    exit 1
fi
echo "  Terraform: $(terraform version -json | python3 -c 'import sys,json;print(json.load(sys.stdin)["terraform_version"])' 2>/dev/null || terraform version | head -1)"

# kubectl
if ! command -v kubectl &>/dev/null; then
    echo "ERROR: kubectl not found. Install: https://kubernetes.io/docs/tasks/tools/"
    exit 1
fi
echo "  kubectl: $(kubectl version --client -o json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["clientVersion"]["gitVersion"])' 2>/dev/null || echo 'installed')"

# Helm
if ! command -v helm &>/dev/null; then
    echo "ERROR: helm not found. Install: https://helm.sh/docs/intro/install/"
    exit 1
fi
echo "  Helm: $(helm version --short 2>/dev/null)"

# Docker
if ! command -v docker &>/dev/null; then
    echo "ERROR: docker not found. Install Docker Desktop."
    exit 1
fi
echo "  Docker: $(docker version --format '{{.Client.Version}}' 2>/dev/null || echo 'installed')"

echo "  Pre-flight: OK"
echo ""

# -----------------------------------------------------------
# Step 1: Terraform — Provision AWS Infrastructure
# -----------------------------------------------------------
if [ "$SKIP_INFRA" = false ]; then
    echo "========================================"
    echo "  Step 1: Terraform Apply"
    echo "========================================"

    cd "$PROJECT_DIR/infra/terraform"

    # Check that terraform.tfvars exists
    if [ ! -f terraform.tfvars ]; then
        echo "ERROR: infra/terraform/terraform.tfvars not found."
        echo "  Copy terraform.tfvars.example to terraform.tfvars and set your db_password."
        exit 1
    fi

    terraform init -upgrade
    terraform plan -out=tfplan
    echo ""
    read -p "Apply this plan? (yes/no): " apply_confirm
    if [ "$apply_confirm" != "yes" ]; then
        echo "Terraform apply cancelled."
        exit 1
    fi
    terraform apply tfplan
    rm -f tfplan

    echo ""
    echo "Terraform outputs:"
    terraform output
    cd "$PROJECT_DIR"
    echo ""
else
    echo "Step 1: Terraform — SKIPPED (--skip-infra)"
    echo ""
fi

# -----------------------------------------------------------
# Step 2: Build & Push Docker Image to ECR
# -----------------------------------------------------------
if [ "$SKIP_BUILD" = false ]; then
    echo "========================================"
    echo "  Step 2: Build & Push Docker Image"
    echo "========================================"
    TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "v0.1.0")
    bash "$SCRIPT_DIR/build_push.sh" "$TAG"
    echo ""
else
    echo "Step 2: Docker Build — SKIPPED (--skip-build)"
    echo ""
fi

# -----------------------------------------------------------
# Step 3: Bootstrap EKS Cluster
# -----------------------------------------------------------
if [ "$SKIP_BOOTSTRAP" = false ]; then
    echo "========================================"
    echo "  Step 3: Bootstrap EKS Cluster"
    echo "========================================"
    bash "$SCRIPT_DIR/bootstrap_cluster.sh"
    echo ""
else
    echo "Step 3: Cluster Bootstrap — SKIPPED (--skip-bootstrap)"
    echo ""
fi

# -----------------------------------------------------------
# Step 4: Initialize Cloud Databases
# -----------------------------------------------------------
echo "========================================"
echo "  Step 4: Initialize Cloud Databases"
echo "========================================"
echo "  (Qdrant collections, Neo4j indexes, Postgres tables)"

# Get endpoints from Terraform outputs
cd "$PROJECT_DIR/infra/terraform"
DB_ENDPOINT=$(terraform output -raw aurora_db_endpoint 2>/dev/null || echo "")
REDIS_ENDPOINT=$(terraform output -raw redis_primary_endpoint 2>/dev/null || echo "")
S3_BUCKET=$(terraform output -raw s3_documents_bucket_name 2>/dev/null || echo "")
cd "$PROJECT_DIR"

echo "  Aurora:  ${DB_ENDPOINT:-'(not available yet — run kubectl port-forward)'}"
echo "  Redis:   ${REDIS_ENDPOINT:-'(not available yet)'}"
echo "  S3:      ${S3_BUCKET:-'(not available yet)'}"
echo ""
echo "  NOTE: Cloud DB init requires network access to the cluster."
echo "  If running from outside the VPC, use kubectl port-forward first:"
echo ""
echo "    kubectl port-forward svc/qdrant 6333:6333 &"
echo "    kubectl port-forward svc/neo4j 7687:7687 &"
echo ""
echo "  Then run: python3 scripts/init_cloud.py"
echo ""

# -----------------------------------------------------------
# Step 5: Smoke Test
# -----------------------------------------------------------
echo "========================================"
echo "  Step 5: Verify Deployment"
echo "========================================"

echo "Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app=api --timeout=120s 2>/dev/null || \
    echo "  API pods not ready yet (may still be starting)"

echo ""
echo "Pod status:"
kubectl get pods -o wide 2>/dev/null || echo "  (kubectl not connected to cluster)"

echo ""
echo "Services:"
kubectl get svc 2>/dev/null || echo "  (kubectl not connected to cluster)"

echo ""
echo "========================================"
echo "  Deployment Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Port-forward to test locally:"
echo "     kubectl port-forward svc/api-service 8000:80"
echo "     curl http://localhost:8000/health/readiness"
echo ""
echo "  2. Initialize cloud databases:"
echo "     python3 scripts/init_cloud.py"
echo ""
echo "  3. Get Ingress URL:"
echo "     kubectl get ingress"
echo ""
echo "  4. Run smoke test:"
echo "     bash scripts/smoke_test.sh"
echo ""
echo "  5. Monitor costs:"
echo "     https://console.aws.amazon.com/cost-management/home"
echo ""
