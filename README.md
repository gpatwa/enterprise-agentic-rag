# Compass Agentic Product Monorepo

![Architecture](https://img.shields.io/badge/Architecture-Agentic%20LangGraph-blueviolet)
![Orchestration](https://img.shields.io/badge/Orchestration-LangGraph%20%2B%20Ray-orange)
![Cloud](https://img.shields.io/badge/Cloud-AWS%20%7C%20Azure-blue)
![Analytics](https://img.shields.io/badge/Analytics-Text--to--SQL%20%2B%20Charts-green)
![Multimodal](https://img.shields.io/badge/Multimodal-Gemini%20Embedding-red)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)

Compass contains two independently deployable products built on explicit shared
contracts: Resolution Intelligence for support teams and conversational
analytics for commerce operators. Product APIs, web apps, tests, configuration,
and release gates are isolated even though they share one repository.

### Why This Platform

| Business Need | How It's Solved |
|--------------|----------------|
| **Reduce repeat support work** | Support Resolution turns tickets and knowledge into cited playbooks, reviewed commands, local execution artifacts, and audit history |
| **Ask business questions** | The standalone Analytics product generates guarded read-only SQL and renders result tables, charts, and SQL evidence |
| **Multimodal understanding** | Gemini Embedding supports text + image retrieval — ingest PDFs with diagrams, photos, screenshots alongside text documents |
| **Business context that makes answers useful** | 4-layer Context Architecture (glossary, metadata, code/pipeline, business rules) enriches every response with institutional knowledge |
| **Data residency & compliance** | Control Plane / Data Plane split — customer data never leaves their cloud region; mTLS secures every cross-plane call |
| **Zero vendor lock-in** | Provider-abstraction layer — swap LLMs (vLLM ↔ OpenAI), vector DBs, storage, and secrets backends with a single env var |
| **Multi-tenant SaaS at scale** | Per-tenant auth, rate limiting, usage metering, and isolated data planes — onboard new customers without redeploying |
| **Multi-cloud portability** | Identical codebase deploys to AWS EKS and Azure AKS with cloud-specific Terraform, Helm, and secrets integrations |

### Technology Stack

Built on **FastAPI**, **React**, **LangGraph**, **Qdrant**, **Neo4j**,
**PostgreSQL**, **Ray/vLLM**, and **Vega-Lite**, with versioned Pydantic
contracts under `packages/platform_contracts`.

## Quick Start (Local Development)

```bash
# 1. Install Python dependencies
make install

# 2. Start local databases (Postgres, Redis, Qdrant, Neo4j, MinIO)
make up

# 3. Configure environment
cp .env.example .env
# Edit .env: set LLM_PROVIDER, EMBED_MODEL, etc.

# 4. Initialize datastores (tables, collections, indexes, buckets)
make init

# 5. Ingest sample documents
python3 scripts/ingest_local.py --sample

# 6. Start the support API and web app in separate terminals
make dev
make dev-support-web
```

Open the support product at `http://localhost:5173/` and its API at
`http://localhost:8080/`.

For analytics, load the demo dataset and start its independent deployables:

```bash
make seed-olist
make dev-analytics-api
make dev-analytics-web
```

Open Analytics at `http://localhost:5174/` and its API at
`http://localhost:8090/`.

| Component       | Service                 | Port        |
|----------------|------------------------|-------------|
| LLM + Embed    | Ollama or OpenAI API   | 11434 / API |
| Vector DB      | Qdrant (Docker)        | 6333        |
| Graph DB       | Neo4j (Docker)         | 7474 / 7687 |
| SQL DB         | Postgres (Docker)      | 5432        |
| Cache          | Redis (Docker)         | 6379        |
| Object Storage | MinIO (Docker)         | 9000 / 9001 |

## Architecture Overview

```text
apps/support-web       -> services/api              -> support data + retrieval
apps/analytics-web     -> services/analytics-api    -> read-only analytics DB
                                  |
                                  v
                    packages/platform_contracts
```

The support API does not import, initialize, route, or stream analytics code.
The analytics API owns SQL generation, schema grounding, safety checks, and
chart result contracts.

### Control Plane / Data Plane (SaaS Mode)

For multi-tenant SaaS deployments with data residency requirements, the platform splits into two independent services:

```
                     +---------------------------+
                     |     Control Plane (SaaS)  |
                     |  Auth, Routing, Rate Limit|
                     |  Tenant & Usage Mgmt      |
                     +------+--------+-----------+
                            |        |
               REST + mTLS  |        |  REST + mTLS
                            v        v
              +-------------+--+  +--+-------------+
              | Data Plane A   |  | Data Plane B   |
              | Customer: Acme |  | Customer: Globex|
              | Region: eu-w-1 |  | Region: us-e-1 |
              | LLM + Qdrant + |  | LLM + Qdrant + |
              | Neo4j + PG     |  | Neo4j + PG     |
              +----------------+  +----------------+
```

| Mode | `DEPLOYMENT_MODE` | Use Case |
|------|-------------------|----------|
| `monolith` | (default) | Single-instance dev/prod |
| `control_plane` | CP only | SaaS management: auth, routing, proxy, admin |
| `data_plane` | DP only | Customer-deployed: query processing, single-tenant |

See [Architecture docs](docs/architecture.md#11-control-plane--data-plane-architecture) for full details.

### Key Design Principles

- **Agentic reasoning** via LangGraph state machine (plan, retrieve, respond, evaluate)
- **Hybrid retrieval** combining vector search (Qdrant) + knowledge graph (Neo4j) + optional re-ranking
- **Dedicated embedding model** (`nomic-embed-text` / `bge-m3`) separate from the generative LLM
- **Multi-cloud** --- identical codebase runs on AWS EKS or Azure AKS
- **Multi-tenant** --- per-tenant data isolation, config, rate limits, and auth
- **Control plane / data plane** --- SaaS-ready split with data residency, mTLS, per-tenant rate limiting
- **Context layer enrichment** --- optional 4-layer business context (glossary, metadata, code/pipeline, business rules) injected at query time
- **Product isolation** --- separate API/web containers, configuration, tests, and CI gates
- **Shared contracts** --- versioned request/response models without cross-product domain imports
- **Provider-abstraction** --- every component (LLM, storage, vector DB, secrets, reranker) is swappable via env vars

### Provider Abstraction

| Component | Env Var | Options |
|-----------|---------|---------|
| LLM | `LLM_PROVIDER` | `ray` (self-hosted vLLM), `openai` |
| Embeddings | `EMBED_PROVIDER` / `EMBED_MODEL` | `ray` + `nomic-embed-text`, `openai` + `text-embedding-3-small` |
| Re-ranker | `RERANKER_PROVIDER` | `none`, `llm` (LLM-based scoring), `cross_encoder` (dedicated model) |
| Context Layers | `CONTEXT_LAYERS_ENABLED` | `false` (off), `true` (glossary, metadata, code, business rules) |
| Vector DB | `VECTORDB_PROVIDER` | `qdrant` |
| Graph DB | `GRAPHDB_PROVIDER` | `neo4j`, `none` (disable) |
| Storage | `STORAGE_PROVIDER` | `s3` (AWS), `azure_blob` (Azure) |
| Secrets | `SECRETS_PROVIDER` | `env`, `aws_sm` (Secrets Manager), `azure_kv` (Key Vault) |

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture & Design](docs/architecture.md) | System design, agentic pipeline, retrieval strategies, multi-tenancy, CP/DP split |
| [AWS Deployment](docs/deployment-aws.md) | EKS provisioning, staging/prod environments, bootstrap, cost management |
| [Azure Deployment](docs/deployment-azure.md) | AKS provisioning, Workload Identity, Key Vault integration |
| [Azure Remote Docker Development](docs/azure-remote-dev.md) | Automated Azure VM development host, Docker bootstrap, sync, tunnels, and lifecycle |
| [Azure Analytics Deployment](docs/deployment-azure.md#analytics-product) | Separate analytics API/web images, Helm releases, Key Vault sync, and manual workflow |
| [Public Landing](docs/deployment-azure.md#public-landing-deployment) | Azure Static Web Apps production landing deployment |
| [API Reference & Chat UI](docs/api-reference.md) | Endpoints (monolith + CP/DP), streaming protocol, sample queries, Chat UI |
| [Local Demo Readiness](docs/LOCAL_DEMO_READINESS.md) | Local-only demo checklist, acceptance gates, and caveats |
| [Resolution Intelligence Architecture](docs/resolution-intelligence-architecture.md) | Support memory, hybrid retrieval, trust gates, action commands, and audit |
| [Prospect Support Case Study](docs/PROSPECT_SUPPORT_CASE_STUDY.md) | Customer-facing Resolution Intelligence story for reducing repeat support tickets |
| [Agentic AI Platform EM Case Study](docs/agentic-ai-platform-em-case-study.md) | Engineering management strategy: business case, team topology, governance, roadmap, SLOs, FinOps, and operating model |
| [Operations Guide](docs/operations.md) | CI/CD, observability, testing, security, troubleshooting, split-plane ops |
| [Security](docs/security.md) | Security model, mTLS, API key auth, rate limiting, threat model |
| [Scaling](docs/scaling.md) | Autoscaling strategy, per-tenant data plane scaling, capacity planning |
| [Request Flow](docs/request_flow.md) | Step-by-step query lifecycle (monolith + split-plane modes) |
| [Roadmap](docs/ROADMAP.md) | Enterprise features, SaaS connectors, zero trust roadmap |
| [Enterprise Analytics Execution Plan](docs/ENTERPRISE_ANALYTICS_EXECUTION_PLAN.md) | Catalog-neutral analytics architecture, phased delivery gates, and model-ready delegation plan |
| [Enterprise Analytics Task Packets](docs/execution/enterprise-analytics/README.md) | Initial bounded assignments with file ownership, acceptance tests, and handoff rules |
| [Immersive Discovery Execution Plan](docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md) | Separate Roblox-like discovery vertical, synthetic-data strategy, multi-stage ranking, and Luna-ready task graph |
| [Immersive Discovery Task Packets](docs/execution/immersive-discovery/README.md) | Bounded IMD assignments, dispatch waves, acceptance evidence, and local-only execution rules |

## Make Commands

```
Support product:
  make install               Install Python dependencies
  make up                    Start local DBs via Docker Compose
  make init                  Initialize DBs, collections, indexes, buckets
  make dev                   Run FastAPI server locally (hot reload, port 8080)
  make demo-ready-local      Seed demo data and run local demo acceptance
  make dev-support-web       Run support web (port 5173)
  make test                  Run support and analytics API suites
  make down                  Stop local DBs

Analytics product:
  make install-analytics     Install standalone API dependencies
  make seed-olist            Load the commerce demo dataset
  make dev-analytics-api     Run analytics API (port 8090)
  make dev-analytics-web     Run analytics web (port 5174)
  make test-analytics        Run analytics API tests

All local product containers:
  make dev-products          Build and run both products with Compose

Split-Plane:
  make dev-control-plane     Run control plane locally (port 8001)
  make dev-data-plane        Run data plane locally (port 8080)
  make dev-split             Run both planes via Docker Compose
  make test-control-plane    Run control plane tests (48 tests)
  make test-data-plane       Run data plane tests (18 tests)
  make test-all              Run all tests (198 tests across 3 suites)

Cloud:
  make azure-dev-up          Provision remote Azure Docker development host
  make azure-dev-tunnel      Forward remote app/API/search ports locally
  make azure-dev-stop        Deallocate remote development compute
  make infra                 Provision AWS prod infrastructure (Terraform)
  make infra-staging         Provision AWS staging infrastructure
  make bootstrap             Bootstrap prod EKS cluster
  make bootstrap-staging     Bootstrap staging EKS cluster
  make deploy-staging        Full staging deploy (infra + bootstrap)
```

## Project Structure

```
scalable-rag-pipeline/
+-- apps/
|   +-- support-web/              # Resolution Intelligence React product
|   +-- analytics-web/            # Commerce analytics React product
+-- packages/
|   +-- platform_contracts/       # Versioned cross-product API contracts
+-- services/
|   +-- api/                      # Support/RAG API (analytics-free)
|   |   +-- app/
|   |   |   +-- agents/           # LangGraph nodes (planner, retriever, context_enricher, responder, evaluator)
|   |   |   +-- context/          # Context layer architecture (glossary, metadata, business rules, code context)
|   |   |   +-- clients/          # Provider-abstracted clients
|   |   |   |   +-- vectordb/     # Qdrant (Protocol + Factory)
|   |   |   |   +-- graphdb/      # Neo4j (Protocol + Factory)
|   |   |   |   +-- storage/      # S3 / Azure Blob (Protocol + Factory)
|   |   |   |   +-- secrets/      # env / AWS SM / Azure KV (Protocol + Factory)
|   |   |   |   +-- reranker/     # none / LLM / cross-encoder (Protocol + Factory)
|   |   |   +-- auth/             # JWT, JWKS, multi-tenant auth
|   |   |   +-- tenants/          # Per-tenant config & registry
|   |   |   +-- memory/           # Postgres chat history
|   |   +-- static/index.html     # Legacy operational fallback UI
|   |   +-- tests/                # Support/RAG API tests
|   |   +-- Dockerfile
|   +-- analytics-api/            # Standalone text-to-SQL product API
|   |   +-- app/analytics/        # Schema, safety, engine, formatter
|   |   +-- tests/
|   |   +-- Dockerfile
|   +-- control-plane/            # Control Plane: SaaS management layer
|   |   +-- app/
|   |   |   +-- auth/             # JWT auth (local + JWKS)
|   |   |   +-- middleware/       # Per-tenant rate limiting (sliding window)
|   |   |   +-- models/           # Tenant, DataPlane, UsageEvent (SQLAlchemy)
|   |   |   +-- proxy/            # Streaming proxy, mTLS, tenant routing
|   |   |   +-- registry/         # Data plane health monitor
|   |   |   +-- routes/           # Auth, tenants, data planes, proxy, usage, health
|   |   +-- main.py               # FastAPI app (port 8001)
|   |   +-- tests/                # 48 control plane tests
|   |   +-- Dockerfile
|   +-- data-plane/               # Data Plane: customer-deployed query processing
|       +-- app/
|       |   +-- auth/             # API key validation + user context forwarding
|       |   +-- registration/     # Heartbeat loop to control plane
|       |   +-- routes/           # Chat, upload, health
|       +-- main.py               # FastAPI app (port 8080)
|       +-- tests/                # 18 data plane tests
|       +-- Dockerfile
+-- scripts/                      # Bootstrap, init, ingest, debug
+-- deploy/
|   +-- helm/api/                 # API Helm chart + values-{staging,prod,azure}.yaml
|   +-- helm/qdrant/              # Qdrant Helm values
|   +-- helm/neo4j/               # Neo4j Helm values
|   +-- karpenter/                # NodePool + EC2NodeClass (envsubst templates)
|   +-- ray/                      # RayCluster + RayServe manifests
|   +-- ingress/                  # NGINX Ingress rules
|   +-- secrets/                  # ExternalSecret manifests
+-- infra/terraform/              # AWS infrastructure (EKS, Aurora, Redis, S3, IAM)
|   +-- envs/staging.tfvars       # Staging variables
|   +-- azure/                    # Azure infrastructure (AKS, PostgreSQL, Redis, Blob, ACR)
+-- eval/                         # RAG evaluation datasets
+-- .github/workflows/            # CI (lint + test) + CD (deploy)
```

## License

MIT
