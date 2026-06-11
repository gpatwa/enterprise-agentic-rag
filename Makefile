# Makefile

.PHONY: help install dev up down stop init support-demo demo-ready-local deploy infra build bootstrap init-cloud smoke-test verify destroy test ingest \
       infra-staging bootstrap-staging deploy-staging deploy-aws \
       deploy-azure infra-azure build-azure bootstrap-azure deploy-api-azure destroy-azure \
       pause-azure resume-azure import-azure \
       verify-cleanup verify-cleanup-delete verify-cleanup-azure verify-cleanup-azure-delete \
       setup lint format \
       dev-control-plane dev-data-plane dev-split test-control-plane test-data-plane test-all

help:
	@echo "RAG Platform Commands:"
	@echo ""
	@echo "  Local Development:"
	@echo "    make install       - Install Python dependencies"
	@echo "    make up            - Start local DBs (Docker)"
	@echo "    make init          - Initialize local DBs, collections, indexes"
	@echo "    make dev           - Run FastAPI server locally (hot reload)"
	@echo "    make support-demo  - Validate Resolution Intelligence demo workflow"
	@echo "    make demo-ready-local - Start local deps, seed demo data, and run demo acceptance"
	@echo "    make ingest FILE=x - Ingest a file, directory, or --sample"
	@echo "    make down          - Stop local DBs (Docker only)"
	@echo "    make stop          - Stop everything (API + Docker + stale processes)"
	@echo "    make test          - Run tests"
	@echo ""
	@echo "  AWS Deployment:"
	@echo "    make deploy-aws       - Full deploy: Terraform + Build + Bootstrap (first time, prod)"
	@echo "    make infra            - Apply Terraform (prod)"
	@echo "    make infra-staging    - Apply Terraform (staging)"
	@echo "    make build            - Build & push Docker image to ECR"
	@echo "    make bootstrap        - Bootstrap EKS cluster (prod)"
	@echo "    make bootstrap-staging- Bootstrap EKS cluster (staging)"
	@echo "    make init-cloud       - Initialize cloud databases (prod)"
	@echo "    make deploy           - Helm upgrade API only (prod, code changes)"
	@echo "    make deploy-staging   - Helm upgrade API only (staging, code changes)"
	@echo "    make verify           - Full post-deploy verify (pods + DB init + tests + UI)"
	@echo "    make smoke-test       - Run smoke tests only"
	@echo "    make destroy          - Tear down ALL AWS resources (prod)"
	@echo ""
	@echo "  Azure Deployment:"
	@echo "    make deploy-azure      - Full deploy: Terraform + Build + Bootstrap (first time)"
	@echo "    make infra-azure       - Apply Azure Terraform only"
	@echo "    make build-azure       - Build & push Docker image to ACR"
	@echo "    make bootstrap-azure   - Bootstrap AKS cluster (K8s resources)"
	@echo "    make deploy-api-azure  - Helm upgrade API only (code changes)"
	@echo "    make pause-azure       - Pause billing: stop Postgres, delete Redis, release IPs, prune ACR, stop App Service, trim Log Analytics (~\$$19/day saved)"
	@echo "    make resume-azure      - Resume: start Postgres + App Service back up (Redis recreated on next deploy)"
	@echo "    make import-azure      - Import manually-created resources into Terraform state (run once)"
	@echo "    make destroy-azure     - Tear down ALL Azure resources + verify"
	@echo ""
	@echo "  Developer Setup:"
	@echo "    make setup         - Install deps + pre-commit hooks"
	@echo "    make lint          - Run ruff linter"
	@echo "    make format        - Auto-fix lint + format code"
	@echo ""
	@echo "  Split-Plane Development:"
	@echo "    make dev-control-plane  - Run control plane locally"
	@echo "    make dev-data-plane     - Run data plane locally"
	@echo "    make dev-split          - Run both planes via Docker Compose"
	@echo "    make test-control-plane - Run control plane tests"
	@echo "    make test-data-plane    - Run data plane tests"
	@echo "    make test-all           - Run all tests (monolith + split)"
	@echo ""
	@echo "  Quick start (local):  make setup && make up && make init && make dev"
	@echo "  Quick start (AWS):    make deploy-aws && make verify"
	@echo "  Quick start (Azure):  make deploy-azure"
	@echo ""
	@echo "  Post-Destroy Verification:"
	@echo "    make verify-cleanup              - Check for orphaned AWS resources"
	@echo "    make verify-cleanup-delete       - Check + delete orphaned AWS resources"
	@echo "    make verify-cleanup-azure        - Check for orphaned Azure resources"
	@echo "    make verify-cleanup-azure-delete - Check + delete orphaned Azure resources"
	@echo ""
	@echo "  Quick start (split):  make up && make dev-split"

# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

setup:
	pip install pre-commit && pre-commit install
	pip install -r services/api/requirements.txt
	pip install pytest pytest-asyncio ruff

install:
	pip install -r services/api/requirements.txt

lint:
	ruff check

format:
	ruff check --fix && ruff format

up:
	docker compose up -d

down:
	docker compose down

stop:
	./scripts/shutdown.sh

init:
	python3 scripts/init_local.py

support-demo:
	@python3 scripts/support_demo_acceptance.py $${API_BASE_URL:+--base-url "$$API_BASE_URL"}

demo-ready-local:
	@$(MAKE) up
	@$(MAKE) init
	@$(MAKE) seed-alpha
	@curl -fsS "$${API_BASE_URL:-http://localhost:8080}/health/liveness" >/dev/null || \
		(echo "API is not running. Start it locally with: cd services/api && uvicorn main:app --host 0.0.0.0 --port 8080 --env-file ../../.env" >&2; exit 1)
	@$(MAKE) support-demo

dev:
	cd services/api && uvicorn main:app --reload --host 0.0.0.0 --port 8080 --env-file ../../.env

ingest:
	@if [ -z "$(FILE)" ]; then \
		echo "Usage:"; \
		echo "  make ingest FILE=report.pdf          # ingest a file"; \
		echo "  make ingest FILE=./docs/             # ingest a directory"; \
		echo "  make ingest FILE=--sample            # ingest sample data"; \
		echo "  make ingest FILE=photo.png            # ingest image (multimodal)"; \
		exit 1; \
	fi
	@set -a && . ./.env && set +a && \
	if [ "$(FILE)" = "--sample" ]; then \
		python3 scripts/ingest_local.py --sample; \
	else \
		python3 scripts/ingest_local.py "$(FILE)"; \
	fi

test:
	pytest

seed-context:
	python3 scripts/seed_context_layers.py

seed-olist:
	python3 scripts/seed_olist.py

# Internal-alpha seed: sample threads, saved questions, glossary, and a
# demo MCP connection. Idempotent. Set MCP_ENCRYPTION_KEY to also seed
# the MCP demo connection (otherwise the rest still seeds and MCP is skipped).
seed-alpha:
	python3 scripts/seed_alpha.py

# Generic dataset loader — works with any CSV dataset
# Usage:
#   make seed-dataset NAME=olist PATH=data/olist/
#   make seed-dataset NAME=sales KAGGLE=username/sales-data
#   make seed-dataset NAME=hr PATH=data/hr/ PREFIX=hr_
seed-dataset:
	@if [ -z "$(NAME)" ]; then \
		echo "Usage:"; \
		echo "  make seed-dataset NAME=olist PATH=data/olist/"; \
		echo "  make seed-dataset NAME=sales KAGGLE=user/dataset"; \
		echo "  make seed-dataset NAME=hr PATH=data/hr/ PREFIX=hr_"; \
		exit 1; \
	fi
	@ARGS="--name $(NAME)"; \
	if [ -n "$(KAGGLE)" ]; then ARGS="$$ARGS --kaggle $(KAGGLE)"; fi; \
	if [ -n "$(PREFIX)" ]; then ARGS="$$ARGS --prefix $(PREFIX)"; fi; \
	if [ -n "$(FORCE)" ]; then ARGS="$$ARGS --force"; fi; \
	if [ -n "$(PATH)" ]; then python3 scripts/seed_dataset.py $(PATH) $$ARGS; \
	else python3 scripts/seed_dataset.py $$ARGS; fi

# ============================================================
# AWS DEPLOYMENT
# ============================================================

# Full deployment (first time): Terraform + Docker + EKS bootstrap
deploy-aws:
	./scripts/deploy_aws.sh

# Terraform only: provision VPC, EKS, Aurora, Redis, S3
infra:
	cd infra/terraform && terraform init -upgrade && terraform apply

# Build Docker image and push to ECR
build:
	./scripts/build_push.sh

# Bootstrap EKS cluster: KubeRay, Qdrant, Neo4j, Ray, Ingress, API
bootstrap:
	./scripts/bootstrap_cluster.sh

# Initialize cloud databases (Qdrant collections, Neo4j indexes)
init-cloud:
	python3 scripts/init_cloud.py

# Helm upgrade API only (for code changes after initial deploy)
deploy:
	@ACCOUNT_ID=$$(aws sts get-caller-identity --query Account --output text); \
	TAG=$$(git rev-parse --short HEAD 2>/dev/null || echo "v0.1.0"); \
	helm upgrade --install api deploy/helm/api \
		--set image.repository="$${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/rag-backend-api" \
		--set image.tag="$${TAG}" \
		--namespace default

# Full post-deploy verification (pods + port-forward + DB init + smoke test + UI)
verify:
	./scripts/post_deploy_verify.sh

# Smoke tests only (requires port-forward already running)
smoke-test:
	./scripts/smoke_test.sh

# Destroy ALL AWS cloud resources (requires confirmation)
destroy:
	./scripts/cleanup.sh
	@echo ""
	@echo "Running post-destroy verification..."
	./scripts/verify-cleanup.sh

verify-cleanup:
	./scripts/verify-cleanup.sh

verify-cleanup-delete:
	./scripts/verify-cleanup.sh --delete

# Terraform for staging (isolated state key + staging.tfvars)
infra-staging:
	cd infra/terraform && \
	terraform init -upgrade -reconfigure \
	    -backend-config="key=staging/terraform.tfstate" && \
	terraform apply -var-file=envs/staging.tfvars

# Bootstrap staging EKS cluster (uses staging cluster name + staging values)
bootstrap-staging:
	CLUSTER_NAME=rag-platform-staging \
	HELM_VALUES_FILE=deploy/helm/api/values-staging.yaml \
	./scripts/bootstrap_cluster.sh

# Helm upgrade API only on staging
deploy-staging:
	@ACCOUNT_ID=$$(aws sts get-caller-identity --query Account --output text); \
	TAG=$$(git rev-parse --short HEAD 2>/dev/null || echo "v0.1.0"); \
	aws eks update-kubeconfig --name rag-platform-staging --region us-east-1; \
	helm upgrade --install api deploy/helm/api \
		-f deploy/helm/api/values-staging.yaml \
		--set image.repository="$${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/rag-backend-api" \
		--set image.tag="$${TAG}" \
		--namespace default

# ============================================================
# AZURE DEPLOYMENT
# ============================================================

# Full Azure deployment (first time): Terraform + Docker + AKS bootstrap
deploy-azure:
	./scripts/deploy_azure.sh

# Azure Terraform only: provision VNet, AKS, PostgreSQL, Redis, Storage, ACR
infra-azure:
	cd infra/terraform/azure && terraform init -upgrade && terraform apply

# Build Docker image and push to ACR
build-azure:
	CLOUD_PROVIDER=azure ./scripts/build_push.sh

# Bootstrap AKS cluster: KubeRay, Qdrant, Neo4j, Ingress, API
bootstrap-azure:
	./scripts/bootstrap_cluster_azure.sh

# Helm upgrade API only on AKS (for code changes after initial deploy)
deploy-api-azure:
	@ACR_NAME=$${ACR_NAME:-ragplatformacr}; \
	TAG=$$(git rev-parse --short HEAD 2>/dev/null || echo "v0.1.0"); \
	helm upgrade --install api deploy/helm/api \
		-f deploy/helm/api/values-azure.yaml \
		--set image.repository="$${ACR_NAME}.azurecr.io/rag-backend-api" \
		--set image.tag="$${TAG}" \
		--namespace default

# Import manually-created Azure resources into Terraform state (run once before first apply)
import-azure:
	./scripts/terraform_import_azure.sh

# Stop AKS + Postgres, delete Redis, release orphaned IPs, prune ACR — saves most daily Azure cost.
# No durable data loss. Reversible with make resume-azure + make infra-azure.
# Use --force flag to skip confirmations: make pause-azure ARGS=--force
pause-azure:
	./scripts/pause_azure.sh $(ARGS)

# Start Postgres back up. Redis is recreated on next make infra-azure / deploy-azure.
resume-azure:
	./scripts/resume_azure.sh

# Destroy ALL Azure cloud resources (requires confirmation)
destroy-azure:
	./scripts/cleanup_azure.sh
	@echo ""
	@echo "Running post-destroy verification (Azure)..."
	./scripts/verify-cleanup-azure.sh

verify-cleanup-azure:
	./scripts/verify-cleanup-azure.sh

verify-cleanup-azure-delete:
	./scripts/verify-cleanup-azure.sh --delete

# ============================================================
# SPLIT-PLANE DEVELOPMENT
# ============================================================

# Run control plane locally (port 8001)
dev-control-plane:
	cd services/control-plane && ENV=dev uvicorn main:app --reload --host 0.0.0.0 --port 8001

# Run data plane locally (port 8080)
dev-data-plane:
	cd services/data-plane && uvicorn main:app --reload --host 0.0.0.0 --port 8080

# Run both planes via Docker Compose (with all dependencies)
dev-split:
	docker compose --profile split up -d

# Run control plane tests only
test-control-plane:
	pytest services/control-plane/tests/ -x -q

# Run data plane tests only
test-data-plane:
	pytest services/data-plane/tests/ -x -q

# Run all tests (monolith + control plane + data plane)
# Each suite runs in its own pytest session to avoid conftest.py namespace collisions
test-all:
	pytest services/api/tests/ -x -q && \
	pytest services/control-plane/tests/ -x -q && \
	pytest services/data-plane/tests/ -x -q
