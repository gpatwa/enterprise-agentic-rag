#!/bin/bash
# scripts/bootstrap_cluster.sh
# Bootstraps the EKS cluster with all required K8s resources.
# Run this AFTER terraform apply has provisioned the infrastructure.

set -euo pipefail

# Allow overrides via environment variables for staging vs prod
CLUSTER_NAME="${CLUSTER_NAME:-rag-platform-cluster}"
REGION="${REGION:-us-east-1}"
HELM_VALUES_FILE="${HELM_VALUES_FILE:-}"  # Optional extra values file (e.g. values-staging.yaml)
KARPENTER_NODE_ROLE="${KARPENTER_NODE_ROLE:-}"  # Auto-detected if not set

echo "========================================"
echo "  EKS Cluster Bootstrap"
echo "========================================"

# -----------------------------------------------------------
# 1. Configure kubectl
# -----------------------------------------------------------
echo ""
echo "Step 1: Updating kubeconfig..."
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION"
kubectl cluster-info

# -----------------------------------------------------------
# 2. Install NVIDIA Device Plugin (required for GPU nodes)
# -----------------------------------------------------------
echo ""
echo "Step 2: Installing NVIDIA device plugin..."
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.3/nvidia-device-plugin.yml 2>/dev/null || \
    echo "  NVIDIA plugin already installed or namespace issue (non-fatal)"

# -----------------------------------------------------------
# 3. Apply Karpenter NodePools
# -----------------------------------------------------------
echo ""
echo "Step 3: Applying Karpenter NodePools..."
# Auto-detect the Karpenter node role if not set
if [ -z "$KARPENTER_NODE_ROLE" ]; then
    KARPENTER_NODE_ROLE=$(aws iam list-roles \
        --query "Roles[?contains(RoleName, \`${CLUSTER_NAME}-karpenter-node\`) || contains(RoleName, \`karpenter-node\`)].RoleName | [0]" \
        --output text --region "$REGION" 2>/dev/null || echo "")
    if [ -z "$KARPENTER_NODE_ROLE" ] || [ "$KARPENTER_NODE_ROLE" = "None" ]; then
        echo "  WARNING: Could not auto-detect Karpenter node role. Set KARPENTER_NODE_ROLE env var."
        echo "  Skipping NodePool apply."
    else
        echo "  Auto-detected KARPENTER_NODE_ROLE: $KARPENTER_NODE_ROLE"
    fi
fi

if [ -n "$KARPENTER_NODE_ROLE" ] && [ "$KARPENTER_NODE_ROLE" != "None" ]; then
    export KARPENTER_NODE_ROLE CLUSTER_NAME
    envsubst '${KARPENTER_NODE_ROLE} ${CLUSTER_NAME}' < deploy/karpenter/nodepool.yaml | kubectl apply -f -
    echo "  NodePools: general (SPOT) + gpu (SPOT, scale-to-zero)"
fi

# -----------------------------------------------------------
# 4. Install ExternalSecrets Operator
# -----------------------------------------------------------
echo ""
echo "Step 4: Installing External Secrets Operator..."
helm repo add external-secrets https://charts.external-secrets.io 2>/dev/null || true
helm repo update
helm upgrade --install external-secrets external-secrets/external-secrets \
    --namespace external-secrets \
    --create-namespace \
    --version 0.9.11 \
    --wait

# Create ClusterSecretStore for AWS Secrets Manager (non-fatal for dev)
kubectl apply -f - <<'EOF' 2>/dev/null || echo "  ClusterSecretStore skipped (non-fatal)"
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: aws-secrets-manager
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets
            namespace: external-secrets
EOF

# Apply ExternalSecret to pull app secrets (non-fatal — dev uses manual secret)
kubectl apply -f deploy/secrets/external-secrets.yaml 2>/dev/null || \
    echo "  ExternalSecret skipped (using manual app-env-secret for dev)"
echo "  Secrets: using app-env-secret (manual or synced from AWS Secrets Manager)"

# -----------------------------------------------------------
# 5. Install KubeRay Operator
# -----------------------------------------------------------
echo ""
echo "Step 5: Installing KubeRay Operator..."
helm repo add kuberay https://ray-project.github.io/kuberay-helm/ 2>/dev/null || true
helm repo update
helm upgrade --install kuberay-operator kuberay/kuberay-operator \
    --version 1.7.2 \
    --wait

# -----------------------------------------------------------
# 6. Deploy Qdrant (Vector Database)
# -----------------------------------------------------------
echo ""
echo "Step 6: Deploying Qdrant..."
helm repo add qdrant https://qdrant.to/helm 2>/dev/null || true
helm repo update
helm upgrade --install qdrant qdrant/qdrant \
    --namespace default \
    --values deploy/helm/qdrant/values.yaml \
    --wait --timeout 120s

# -----------------------------------------------------------
# 7. Deploy Neo4j (Graph Database)
# -----------------------------------------------------------
echo ""
echo "Step 7: Deploying Neo4j..."
helm repo add neo4j https://helm.neo4j.com/neo4j 2>/dev/null || true
helm repo update
helm upgrade --install neo4j neo4j/neo4j \
    --namespace default \
    --values deploy/helm/neo4j/values.yaml \
    --set neo4j.password="$(kubectl get secret app-env-secret -o jsonpath='{.data.NEO4J_PASSWORD}' 2>/dev/null | base64 -d 2>/dev/null || echo 'password')" \
    --wait --timeout 180s

# -----------------------------------------------------------
# 8. Deploy Ray Cluster (non-fatal — GPU nodes spin up on demand)
# -----------------------------------------------------------
echo ""
echo "Step 8: Deploying Ray Cluster (head node + worker config)..."
kubectl apply -f deploy/ray/ray-cluster.yaml 2>/dev/null || \
    echo "  Ray Cluster skipped (KubeRay CRDs may need a moment)"

echo "  Waiting 30s for Ray head to initialize..."
sleep 30

# -----------------------------------------------------------
# 9. Deploy Ray Serve (LLM + Embeddings) — non-fatal
# -----------------------------------------------------------
echo ""
echo "Step 9: Deploying Ray Serve AI engines..."
echo "  These will trigger Karpenter to provision GPU SPOT nodes on demand."
kubectl apply -f deploy/ray/ray-serve-llm.yaml 2>/dev/null || \
    echo "  Ray Serve LLM skipped (will deploy when GPU nodes are ready)"
kubectl apply -f deploy/ray/ray-serve-embed.yaml 2>/dev/null || \
    echo "  Ray Serve Embed skipped (will deploy when GPU nodes are ready)"

# -----------------------------------------------------------
# 10. Deploy NGINX Ingress
# -----------------------------------------------------------
echo ""
echo "Step 10: Deploying NGINX Ingress..."
# Install NGINX Ingress Controller if not present
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>/dev/null || true
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
    --namespace ingress-nginx \
    --create-namespace \
    --set controller.service.type=LoadBalancer \
    --set "controller.tolerations[0].key=CriticalAddonsOnly" \
    --set "controller.tolerations[0].operator=Exists" \
    --set "controller.tolerations[0].effect=NoSchedule" \
    --wait --timeout 120s || echo "  Ingress controller install (may already exist)"

# Apply ingress routing rules
kubectl apply -f deploy/ingress/nginx.yaml

# -----------------------------------------------------------
# 11. Deploy Backend API
# -----------------------------------------------------------
echo ""
echo "Step 11: Deploying Backend API..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "v0.1.0")

# Build helm command — append extra values file if set (e.g. values-staging.yaml)
HELM_CMD="helm upgrade --install api deploy/helm/api \
    --set image.repository=${ECR_URI}/rag-backend-api \
    --set image.tag=${TAG} \
    --wait --timeout 120s"

if [ -n "${HELM_VALUES_FILE:-}" ]; then
    echo "  Using values override: ${HELM_VALUES_FILE}"
    HELM_CMD="${HELM_CMD} -f ${HELM_VALUES_FILE}"
fi

eval "$HELM_CMD"

# -----------------------------------------------------------
# Summary
# -----------------------------------------------------------
echo ""
echo "========================================"
echo "  Cluster Bootstrap Complete!"
echo "========================================"
echo ""
echo "  Pods:"
kubectl get pods --no-headers 2>/dev/null | while read line; do echo "    $line"; done
echo ""
echo "  Services:"
kubectl get svc --no-headers 2>/dev/null | while read line; do echo "    $line"; done
echo ""
echo "  Ingress:"
kubectl get ingress --no-headers 2>/dev/null | while read line; do echo "    $line"; done
echo ""
echo "  Next: Run 'python3 scripts/init_cloud.py' to initialize databases."
echo "  Monitor: kubectl get pods -w"
echo ""
