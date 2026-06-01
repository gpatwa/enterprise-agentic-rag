#!/bin/bash
# scripts/build_push.sh
# Builds the API Docker image and pushes to the cloud container registry.
# Supports both AWS ECR and Azure ACR via CLOUD_PROVIDER env var.
#
# Usage: ./scripts/build_push.sh [TAG]
#   TAG defaults to git short SHA if not provided.
#
# Environment variables:
#   CLOUD_PROVIDER  — "aws" (default) or "azure"
#   AWS_REGION      — AWS region (default: us-east-1)
#   ACR_NAME        — Azure Container Registry name (required for azure)

set -euo pipefail

CLOUD_PROVIDER="${CLOUD_PROVIDER:-aws}"
REPO_NAME="rag-backend-api"
TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo 'latest')}"
PROVIDER_LABEL=$(printf "%s" "$CLOUD_PROVIDER" | tr '[:lower:]' '[:upper:]')
DOCKER_PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"

echo "========================================"
echo "  Build & Push - ${PROVIDER_LABEL}"
echo "========================================"
echo "  Repo:    $REPO_NAME"
echo "  Tag:     $TAG"
echo "  Platform:$DOCKER_PLATFORM"
echo "========================================"

# -------------------------------------------------------
# Step 1: Build Docker image (same for both providers)
# -------------------------------------------------------
echo ""
echo "Step 1: Building Docker image..."
docker build --platform "$DOCKER_PLATFORM" -t "${REPO_NAME}:${TAG}" -f services/api/Dockerfile services/api/

# -------------------------------------------------------
# Step 2+: Registry-specific login, tag, push
# -------------------------------------------------------

if [ "$CLOUD_PROVIDER" = "aws" ]; then
    # ===================== AWS ECR =====================
    REGION="${AWS_REGION:-us-east-1}"

    echo ""
    echo "  Provider: AWS ECR"
    echo "  Region:   $REGION"

    # Get AWS Account ID
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
    if [ -z "$ACCOUNT_ID" ]; then
        echo "ERROR: Could not get AWS Account ID. Is AWS CLI configured?"
        echo "  Run: aws configure --profile rag-prod"
        exit 1
    fi
    ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
    FULL_IMAGE="${ECR_URI}/${REPO_NAME}:${TAG}"

    echo ""
    echo "Step 2: Creating ECR repository (if not exists)..."
    aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$REGION" 2>/dev/null || \
        aws ecr create-repository \
            --repository-name "$REPO_NAME" \
            --region "$REGION" \
            --image-scanning-configuration scanOnPush=true \
            --image-tag-mutability MUTABLE

    echo ""
    echo "Step 3: Logging into ECR..."
    aws ecr get-login-password --region "$REGION" | \
        docker login --username AWS --password-stdin "$ECR_URI"

    echo ""
    echo "Step 4: Tagging image..."
    docker tag "${REPO_NAME}:${TAG}" "$FULL_IMAGE"
    docker tag "${REPO_NAME}:${TAG}" "${ECR_URI}/${REPO_NAME}:latest"

    echo ""
    echo "Step 5: Pushing to ECR..."
    docker push "$FULL_IMAGE"
    docker push "${ECR_URI}/${REPO_NAME}:latest"

    echo ""
    echo "========================================"
    echo "  Image pushed successfully!"
    echo "  ${FULL_IMAGE}"
    echo "========================================"
    echo ""
    echo "Tip: Update deploy/helm/api/values.yaml with:"
    echo "  repository: ${ECR_URI}/${REPO_NAME}"
    echo "  tag: \"${TAG}\""

elif [ "$CLOUD_PROVIDER" = "azure" ]; then
    # ===================== Azure ACR =====================
    ACR_NAME="${ACR_NAME:-}"
    if [ -z "$ACR_NAME" ]; then
        echo "ERROR: ACR_NAME environment variable is required for Azure."
        echo "  Export ACR_NAME=<your-acr-name>"
        exit 1
    fi
    ACR_URI="${ACR_NAME}.azurecr.io"
    FULL_IMAGE="${ACR_URI}/${REPO_NAME}:${TAG}"

    echo ""
    echo "  Provider: Azure ACR"
    echo "  Registry: $ACR_URI"

    echo ""
    echo "Step 2: Logging into ACR..."
    az acr login --name "$ACR_NAME"

    echo ""
    echo "Step 3: Tagging image..."
    docker tag "${REPO_NAME}:${TAG}" "$FULL_IMAGE"
    docker tag "${REPO_NAME}:${TAG}" "${ACR_URI}/${REPO_NAME}:latest"

    echo ""
    echo "Step 4: Pushing to ACR..."
    docker push "$FULL_IMAGE"
    docker push "${ACR_URI}/${REPO_NAME}:latest"

    echo ""
    echo "========================================"
    echo "  Image pushed successfully!"
    echo "  ${FULL_IMAGE}"
    echo "========================================"
    echo ""
    echo "Tip: Update deploy/helm/api/values-azure.yaml with:"
    echo "  repository: ${ACR_URI}/${REPO_NAME}"
    echo "  tag: \"${TAG}\""

else
    echo "ERROR: Unknown CLOUD_PROVIDER: '${CLOUD_PROVIDER}'"
    echo "  Supported: 'aws', 'azure'"
    exit 1
fi
