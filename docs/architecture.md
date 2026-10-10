# RAG Platform — Architecture

## Core Principles

1. **Multi-cloud by design** — runs on AWS (EKS) and Azure (AKS) with a provider abstraction layer. No cloud lock-in.
2. **Decoupled compute** — the API orchestrator (CPU) is separate from the AI engines (GPU). Each scales independently.
3. **Hybrid retrieval** — combines vector search (semantic meaning) and graph search (entity relationships) for higher accuracy than either alone.
4. **Async ingestion** — document processing runs as a separate Ray pipeline, never blocking query latency.
5. **Zero static credentials** — all secrets live in Key Vault / Secrets Manager, injected at runtime via Workload Identity.

### Architecture Status

For enterprise search, support resolution, personalization, and recommendation,
**OpenSearch is the target and authoritative derived search plane**. It owns
BM25/exact-term fields, dense-vector fields, hybrid retrieval, tenant/ACL filters,
and index-generation metadata. PostgreSQL and object storage remain canonical
system-of-record stores. Qdrant remains only as a legacy/local compatibility
adapter for older generic RAG and multimodal paths; it is not the authority for
the enterprise support-search workflow.

The standalone analytics product is evolving through the
[Agentic Data Stack Execution Plan](AGENTIC_DATA_STACK_EXECUTION_PLAN.md).
Its Archify-generated [animated system diagram](diagrams/agentic-data-stack-system.html)
shows the ontology/context layer, PostgreSQL customer path, and DuckDB
local/data-lake path. The companion
[request workflow](diagrams/agentic-data-stack-request.html) follows the bounded
agent graph, deterministic trust gates, execution, evidence, and reviewed
improvement loop. This analytics path is separately deployable and does not
make the support API its runtime boundary. Diagram sources and update rules are
documented in the [diagram README](diagrams/README.md).

---

## 1. System Architecture (Multi-Cloud)

```mermaid
graph TB
    subgraph Clients["Client Layer"]
        Browser["Browser / Chat UI"]
        ExtAPI["External API Consumers"]
    end

    subgraph CICD["CI/CD (GitHub Actions)"]
        direction LR
        PR["Pull Request\n(feature branch)"]
        CI["CI Pipeline\nlint · test · build · validate"]
        Staging["Manual dispatch\nto Staging"]
        Prod["Manual approval\nto Production"]
        PR --> CI --> Staging --> Prod
    end

    subgraph AWS["AWS Cloud"]
        ALB["ALB\nLoad Balancer"]
        subgraph EKS["EKS Cluster (Karpenter autoscale)"]
            direction TB
            Ingress_AWS["NGINX Ingress\nTLS · Rate Limit"]
            subgraph CPU_AWS["CPU Node Pool"]
                API_AWS["FastAPI\nOrchestrator"]
                Sandbox_AWS["Code Sandbox\n(isolated)"]
            end
            subgraph GPU_AWS["GPU Node Pool"]
                Ray_AWS["Ray Serve"]
                vLLM_AWS["vLLM Engine\nLlama-3-70B"]
                Embed_AWS["Embedding Engine\nnomic-embed-text / bge-m3"]
            end
            Search_AWS["OpenSearch\nEnterprise Search\nBM25 · vector · ACL"]
            Neo4j_AWS["Neo4j\nGraph DB"]
        end
        subgraph Managed_AWS["Managed Services"]
            Aurora["Aurora Postgres\n(chat history)"]
            ElastiCache["ElastiCache Redis\n(cache · sessions)"]
            S3["S3\n(documents)"]
            ECR["ECR\n(container registry)"]
            SM["Secrets Manager\n(credentials)"]
        end
    end

    subgraph Azure["Azure Cloud"]
        AFD["Azure Load Balancer"]
        subgraph AKS["AKS Cluster (native Cluster Autoscaler)"]
            direction TB
            Ingress_AZ["NGINX Ingress\nTLS · Rate Limit"]
            subgraph CPU_AZ["CPU Node Pool"]
                API_AZ["FastAPI\nOrchestrator"]
                Sandbox_AZ["Code Sandbox\n(isolated)"]
            end
            subgraph GPU_AZ["GPU Node Pool"]
                Ray_AZ["Ray Serve"]
                vLLM_AZ["vLLM Engine\nLlama-3-70B"]
                Embed_AZ["Embedding Engine\nnomic-embed-text / bge-m3"]
            end
            Search_AZ["OpenSearch\nEnterprise Search\nBM25 · vector · ACL"]
            Neo4j_AZ["Neo4j\nGraph DB"]
        end
        subgraph Managed_AZ["Managed Services"]
            PgFlex["Postgres Flex\n(chat history)"]
            AzRedis["Azure Cache\nfor Redis"]
            Blob["Blob Storage\n(documents)"]
            ACR["ACR\n(container registry)"]
            KeyVault["Key Vault\n(credentials)"]
        end
    end

    Browser --> ALB & AFD
    ExtAPI --> ALB & AFD

    ALB --> Ingress_AWS --> API_AWS
    AFD --> Ingress_AZ --> API_AZ

    API_AWS <--> Aurora & ElastiCache
    API_AWS --> Ray_AWS & Sandbox_AWS
    Ray_AWS --> vLLM_AWS & Embed_AWS
    Ray_AWS <--> Search_AWS & Neo4j_AWS

    API_AZ <--> PgFlex & AzRedis
    API_AZ --> Ray_AZ & Sandbox_AZ
    Ray_AZ --> vLLM_AZ & Embed_AZ
    Ray_AZ <--> Search_AZ & Neo4j_AZ

    SM -.->|"ESO + IRSA"| API_AWS
    KeyVault -.->|"ESO + Workload Identity"| API_AZ
```

---

## 2. Query Request Flow

```mermaid
sequenceDiagram
    autonumber
    participant U as Client
    participant I as Ingress (NGINX)
    participant A as FastAPI API
    participant C as Semantic Cache (Redis)
    participant LG as LangGraph Agent
    participant E as Embedding Engine (Ray)
    participant S as OpenSearch (BM25 + Vector + ACL)
    participant G as Neo4j (Graph Search)
    participant R as Re-ranker
    participant L as vLLM (Llama-3)
    participant DB as Postgres

    U->>I: POST /api/v1/chat/stream (JWT)
    I->>I: TLS termination · Rate limit check
    I->>A: Forward request
    A->>A: JWT validation · Tenant context injection
    A->>C: Embed query → check semantic cache
    alt Cache HIT (similarity > 0.95)
        C-->>U: Stream cached answer (fast path ~50ms)
    else Cache MISS
        A->>LG: Start LangGraph execution
        LG->>E: Embed query
        par Hybrid retrieval
            E->>S: BM25 + vector search with tenant/ACL filters
        and
            LG->>G: Graph search (entity relationships)
        end
        S-->>LG: Ranked authorized candidates
        G-->>LG: Entity graph context
        LG->>R: Re-rank merged results (filter score < threshold)
        R-->>LG: Top-ranked chunks
        LG->>L: Synthesize answer (chunks + graph + query)
        L-->>U: Stream tokens as SSE
        Note over LG: Evaluator scores answer quality (0-1)
        LG-->>A: Final answer + evaluation score
        A->>DB: Save Q&A (background)
        A->>C: Update semantic cache (background)
    end
```

---

## 3. Document Ingestion Pipeline

```mermaid
flowchart LR
    subgraph Upload
        Client["Client\nUpload"]
        PSU["Presigned URL\n(S3 / Blob)"]
        Client -->|"PUT file directly"| PSU
    end

    subgraph Storage["Object Storage"]
        Bucket["S3 / Blob\nuploads/{tenant}/{user}/{file_id}"]
        PSU --> Bucket
    end

    subgraph Trigger
        Bucket -->|"Object created event"| RayJob
    end

    subgraph RayPipeline["Ray Ingestion Pipeline"]
        direction TB
        RayJob["Ray Job\nOrchestrator"]
        Parse["Parse & Extract\n(unstructured, pytesseract)"]
        Chunk["Text Chunker\n(recursive, semantic)"]
        EmbedI["Embedding Engine\nnomic-embed-text / bge-m3"]
        GraphEx["Graph Extractor\nvLLM (entity/relation)"]

        RayJob --> Parse --> Chunk
        Chunk --> EmbedI & GraphEx
    end

    subgraph Indexes
        OpenSearchIdx["OpenSearch\nLexical + Vector Index"]
        Neo4jIdx["Neo4j\nGraph Index"]
        Chunk -->|"Index text + support metadata"| OpenSearchIdx
        EmbedI -->|"Index dense vectors"| OpenSearchIdx
        GraphEx -->|"Upsert nodes/edges"| Neo4jIdx
    end
```

---

## 4. CI/CD & Developer Lifecycle

```mermaid
flowchart LR
    subgraph Dev["Local Development"]
        Code["Write Code\n(feature branch)"]
        PreCommit["pre-commit hooks\nruff · terraform_fmt\ndetect-private-key"]
        Code --> PreCommit
    end

    subgraph PR["Pull Request"]
        GH["GitHub PR\nto main"]
        PreCommit --> GH
    end

    subgraph CI["CI Pipeline (ci.yml)"]
        direction TB
        Lint["Lint\n(ruff check)"]
        Tests["Tests\n(pytest suite)"]
        DockerBuild["Docker Build\nAPI image"]
        TFValidate["Terraform\nValidate"]
        Lint --> Tests --> DockerBuild --> TFValidate
    end

    subgraph Staging["Staging Deploy (manual)"]
        PushImage_S["Push image\nstaging-sha"]
        HelmS["Helm upgrade\nvalues-staging.yaml\n1 replica · DEBUG logs"]
        PushImage_S --> HelmS
    end

    subgraph Prod["Production Deploy (manual)"]
        Approval["Environment\nApproval Gate"]
        PushImage_P["Re-tag image\nprod-sha"]
        HelmP["Helm upgrade\nvalues-prod.yaml\n2 replicas · WARNING logs"]
        Approval --> PushImage_P --> HelmP
    end

    GH --> CI
    CI -->|"workflow dispatch"| Staging
    Staging -->|"manual trigger"| Prod
```

---

## 5. Secrets & Identity Architecture

```mermaid
flowchart TB
    subgraph Identity["Pod Identity (No Static Credentials)"]
        WI["Azure Workload Identity\n/ AWS IRSA"]
    end

    subgraph Vaults["Secret Stores"]
        KV["Azure Key Vault"]
        SM["AWS Secrets Manager"]
    end

    subgraph ESO["External Secrets Operator"]
        Sync["SecretStore\n(1hr refresh)"]
    end

    subgraph K8s["Kubernetes"]
        Secret["K8s Secret\n(synced)"]
        Pod["API Pod\n(env vars injected)"]
    end

    WI -->|"token exchange"| KV & SM
    KV & SM --> Sync --> Secret --> Pod

    subgraph Stored["Secrets Managed"]
        direction LR
        s1["db-password"]
        s2["redis-primary-key"]
        s3["neo4j-password"]
        s4["jwt-secret-key"]
        s5["openai-api-key"]
    end

    KV & SM -.-> Stored
```

---

## 6. Multi-Tenant Data Isolation

```mermaid
flowchart TD
    JWT["JWT Token\ntenant_id · user_id · role"]

    JWT --> API["FastAPI\nTenantContext injection"]

    API --> PG["Postgres\nWHERE tenant_id = ?"]
    API --> OS["OpenSearch\nfilter: tenant_id + ACL"]
    API --> N4J["Neo4j\nWHERE n.tenant_id = ?"]
    API --> STORE["S3 / Blob\nuploads/{tenant_id}/{user_id}/..."]
    API --> REDIS["Redis\nKey prefix: tenant:{id}:..."]

    style JWT fill:#f5a623,color:#000
    style API fill:#4a90d9,color:#fff
```

---

## 7. Re-Ranking Layer

After OpenSearch hybrid retrieval combines BM25/exact-term and vector candidates,
with optional graph context, an optional re-ranker re-scores documents for relevance:

| Provider | Env Var | Latency | Use Case |
|----------|---------|---------|----------|
| `none` | `RERANKER_PROVIDER=none` | 0ms | Dev (fast iteration) |
| `llm` | `RERANKER_PROVIDER=llm` | ~200ms | Staging (single LLM call scores N docs) |
| `cross_encoder` | `RERANKER_PROVIDER=cross_encoder` | ~50ms | Production (dedicated Ray Serve model) |

**Design decisions:**
- Scores normalized to 0.0–1.0 range
- Threshold filtering (default 0.3) removes irrelevant chunks but always keeps at least 1
- Graceful failure — any error falls back to original document order
- OpenSearch applies tenant/ACL filters before candidates reach the re-ranker
- Graph context is supplemental and never broadens the authorized search scope

---

## 8. Evaluator Node

The final LangGraph node scores answer quality on a 0-1 scale:
- Checks if the answer is grounded in the retrieved sources
- Detects hallucination or unsupported claims
- Score is returned to the client in the SSE stream
- Can be used for automated quality monitoring and feedback loops

---

## 9. Context Layer Architecture

The platform includes an optional **Context Layer Architecture** that enriches every RAG response with structured business knowledge. Inspired by enterprise data agent patterns, it adds four overlapping context layers between the retriever and responder nodes, transforming answers from "here's what the document says" to "here's what it means in your business context."

### Feature Flag

Disabled by default — zero impact on existing behavior:

| Setting | Default | Description |
|---------|---------|-------------|
| `CONTEXT_LAYERS_ENABLED` | `false` | Master toggle for the entire context layer system |
| `CONTEXT_LAYER1_ENABLED` | `true` | Document metadata & usage signals |
| `CONTEXT_LAYER2_ENABLED` | `true` | Human annotations & glossary |
| `CONTEXT_LAYER3_ENABLED` | `true` | Code & pipeline context |
| `CONTEXT_LAYER4_ENABLED` | `true` | Institutional / business rules |
| `CONTEXT_LAYERS_MAX_TOKENS` | `1500` | Token budget for context block |
| `CONTEXT_FRESHNESS_DECAY_DAYS` | `90` | Freshness score half-life (days) |

### Query Flow with Context Layers

```mermaid
flowchart LR
    Q["User Query"] --> P["Planner"]
    P --> R["Retriever\n(vector + graph)"]
    R --> CE["Context Enricher\n(parallel fetch)"]
    CE --> Resp["Responder\n(docs + context)"]
    Resp --> E["Evaluator"]

    subgraph CE_detail["Context Enricher (parallel)"]
        direction TB
        L1["Layer 1: Doc Metadata\nfreshness, usage, tags"]
        L2["Layer 2: Annotations\nglossary, KPIs, notes"]
        L3["Layer 3: Code Context\nETL, SQL, lineage"]
        L4["Layer 4: Business Rules\nterminology, org context"]
    end

    CE -.-> CE_detail
```

### The Four Layers

**Layer 1 — Document Metadata & Usage Signals**
- Fetches freshness scores, access frequency, summaries, and tags for retrieved documents
- Uses exponential decay for freshness scoring (configurable half-life)
- Updates access tracking as a side effect (last accessed, access count)
- Stored in `document_metadata` Postgres table, populated during ingestion

**Layer 2 — Human Annotations & Glossary**
- Matches glossary definitions, KPI formulas, and document notes against query terms
- Uses ILIKE pattern matching with stop-word filtering
- Stored in `annotations` Postgres table, managed via Admin API

**Layer 3 — Code & Pipeline Context**
- Fetches relevant ETL pipeline descriptions, SQL context, API endpoint docs, and data lineage
- Includes upstream/downstream dependency information
- Stored in `code_context` Postgres table, managed via Admin API

**Layer 4 — Institutional / Business Context**
- Fetches business rules, organizational terminology, and role-specific context
- Filtered by `applies_to_roles` matching the requesting user's role
- Priority-ordered (higher priority rules surface first)
- Stored in `business_context` Postgres table, managed via Admin API

### Token Budget & Priority

The assembler merges all layer outputs under a configurable token budget (default 1500 tokens). When the budget is exceeded, layers are prioritized:

1. **Business Rules** (highest priority — domain-critical definitions)
2. **Annotations** (glossary terms directly relevant to the query)
3. **Metadata** (document freshness and usage signals)
4. **Code Context** (pipeline and lineage information)

### Admin API

All context layer data is managed through REST endpoints at `/api/v1/context/`:

- **Annotations**: CRUD for glossary terms, KPI definitions, and document notes
- **Business Rules**: CRUD for terminology, business rules, role-specific context
- **Code Context**: CRUD for ETL pipeline docs, SQL descriptions, data lineage
- **Document Metadata**: Read-only (auto-populated during ingestion)

See [API Reference](api-reference.md#context-layer-admin-api) for full endpoint documentation.

### Data Model

All four tables are tenant-scoped and auto-created on startup via SQLAlchemy:

```
services/api/app/context/
├── __init__.py
├── models.py              # 4 Postgres table models
├── base.py                # ContextLayerProvider protocol
├── layer1_metadata.py     # Document metadata & usage
├── layer2_annotations.py  # Glossary, KPIs, notes
├── layer3_code.py         # Code/pipeline context
├── layer4_business.py     # Business rules, terminology
├── assembler.py           # Orchestrates all layers (parallel fetch + token budget)
└── manager.py             # CRUD operations for admin API
```

---

## 10. Standalone Analytics Product

Analytics is an independent product boundary in the monorepo. It is not a
LangGraph node or feature flag inside the support API. The API, web app,
configuration, tests, Docker images, and CI gates can be released without a
support deployment.

```text
apps/analytics-web
        |
        | packages.platform_contracts.analytics (v1)
        v
services/analytics-api
        |
        +-- schema grounding
        +-- SQL generation and validation
        +-- read-only query execution
        +-- chart specification
        v
analytics Postgres
```

### Query Flow

```
Analytics Web: "What was revenue by month?"
  → POST /api/v1/analytics/query using the shared v1 contract
  → Analytics API builds schema context
  → LLM generates one PostgreSQL SELECT query
  → Safety layer validates statements, tables, columns, and cost
  → Read-only Postgres connection executes with a timeout and row cap
  → API returns rows, timing, SQL evidence, and a Vega-Lite chart spec
  → Analytics Web renders the result workspace
```

### Architecture Components

| Component | File | Purpose |
|-----------|------|---------|
| Shared contract | `packages/platform_contracts/analytics.py` | Versioned query, result, schema, and health models |
| Schema context | `services/analytics-api/app/analytics/schema_context.py` | Table descriptions, columns, joins, and metrics |
| Safety | `services/analytics-api/app/analytics/safety.py` | SELECT-only, keyword, table, column, and cost validation |
| Engine | `services/analytics-api/app/analytics/engine.py` | SQL generation and read-only execution |
| API service | `services/analytics-api/app/service.py` | Contract mapping and chart result assembly |
| Web product | `apps/analytics-web` | Query workspace, table, chart, SQL evidence, and health state |

### Safety Guardrails

- **Read-only connection**: `default_transaction_read_only=on` at connection level
- **SELECT-only validation**: Rejects INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, etc.
- **Keyword blocklist**: Rejects `pg_sleep`, `COPY`, `EXECUTE`, `dblink`, etc.
- **Table allowlist**: Only known dataset tables can be queried
- **Cost guard**: Rejects queries on tables >100K rows without WHERE/LIMIT/GROUP BY
- **Statement timeout**: Default 10 seconds, configurable
- **Row cap**: Results limited to 1,000 rows

### Dataset Loading

The platform includes two seed scripts for loading structured data:

```bash
# Load the built-in Olist e-commerce dataset (100K orders, 8 tables)
make seed-olist

# Load any CSV dataset (auto-discovers schema, relationships, metrics)
make seed-dataset NAME=sales PATH=data/sales/
make seed-dataset NAME=hr KAGGLE=username/hr-analytics PREFIX=hr_
```

The generic loader (`scripts/seed_dataset.py`) auto-generates a `schema_context.yaml` and Python schema module from any CSV collection.

### Ownership Rules

- `services/api` must not import `services/analytics-api`.
- Analytics must not import support models, routes, graph state, or connector code.
- Product services may depend on `packages/platform_contracts` only through
  public versioned models.
- Each product owns its database schema and migrations. Sharing one local
  Postgres process does not imply shared table ownership.
- OpenMetadata, when added, belongs behind an analytics-owned metadata provider.

---

## Component Summary

| Component | AWS | Azure | Purpose |
|-----------|-----|-------|---------|
| Kubernetes | EKS + Karpenter | AKS + native Cluster Autoscaler | Container orchestration, autoscaling |
| API | FastAPI | FastAPI | Query orchestration, auth, streaming |
| AI engines | Ray Serve + vLLM + Embedding | Ray Serve + vLLM + Embedding | LLM inference, embeddings (nomic-embed-text / bge-m3) |
| Re-ranker | none / LLM / cross-encoder | none / LLM / cross-encoder | Post-retrieval relevance scoring |
| Search plane | OpenSearch (private endpoint/provider) | OpenSearch (private endpoint/provider) | BM25, exact-term, vector, hybrid ranking, tenant/ACL filters |
| Legacy vector adapter | Qdrant (compatibility/local only) | Qdrant (compatibility/local only) | Older generic RAG or multimodal paths; not enterprise support authority |
| Graph DB | Neo4j (in-cluster Helm) | Neo4j (in-cluster Helm) | Entity relationship queries |
| Relational DB | Aurora Postgres | Postgres Flexible Server | Chat history, session state |
| Cache | ElastiCache Redis | Azure Cache for Redis | Semantic cache, rate limiting |
| Object storage | S3 | Blob Storage | Document storage, presigned uploads |
| Container registry | ECR | ACR | Docker images |
| Secret store | Secrets Manager + IRSA | Key Vault + Workload Identity | Credential management |
| Ingress | NGINX | NGINX | TLS termination, rate limiting |
| Observability | AWS X-Ray + CloudWatch | Azure Monitor + App Insights | Tracing, logging, metrics |

---

## 11. Control Plane / Data Plane Architecture

The platform supports a **split-plane deployment** for SaaS scenarios with data residency requirements. The monolith can be decomposed into two independent services:

- **Control Plane** — SaaS management layer (your cloud): auth, tenant management, routing, rate limiting, usage tracking
- **Data Plane** — Query processing (customer's cloud/region): LLM inference, embeddings, vector/graph search, chat history

One customer = one dedicated Data Plane. Each data plane runs in the customer's cloud region for data residency compliance.

### Deployment Modes

| Mode | `DEPLOYMENT_MODE` | Use Case |
|------|-------------------|----------|
| `monolith` | (default) | Single-instance dev/prod — everything in one FastAPI process |
| `control_plane` | CP only | SaaS management layer: auth, routing, proxy, admin |
| `data_plane` | DP only | Customer-deployed: query processing in `SINGLE_TENANT_MODE` |

### Split Architecture Diagram

```mermaid
graph TB
    subgraph CP["Control Plane (SaaS Provider)"]
        UI["Chat UI (SPA)"]
        Auth["JWT Auth\n(Local / Auth0 / Azure AD)"]
        TenantMgmt["Tenant CRUD"]
        Router["Proxy Router\n+ Rate Limiter"]
        Registry["Data Plane Registry\n+ Health Monitor"]
        UsageMgmt["Usage Tracking"]
        CPDB["Control Plane DB\n(Tenants, Data Planes, Usage)"]

        UI --> Auth
        Auth --> Router
        Router --> CPDB
        TenantMgmt --> CPDB
        Registry --> CPDB
        UsageMgmt --> CPDB
    end

    subgraph DP1["Data Plane — Customer A (eu-west-1)"]
        DPAuth1["API Key Auth\n(X-DataPlane-Key)"]
        Pipeline1["LangGraph Agent\nPlan → Retrieve → Respond → Evaluate"]
        VDB1["OpenSearch\nBM25 + vector + ACL"]
        GDB1["Neo4j"]
        LLM1["LLM (Ray/OpenAI)"]
        PG1["Postgres\n(chat history)"]

        DPAuth1 --> Pipeline1
        Pipeline1 --> VDB1 & GDB1 & LLM1
        Pipeline1 --> PG1
    end

    subgraph DP2["Data Plane — Customer B (us-east-1)"]
        DPAuth2["API Key Auth"]
        Pipeline2["LangGraph Agent"]
        VDB2["OpenSearch\nBM25 + vector + ACL"]
        LLM2["LLM"]
    end

    Router -->|"REST + mTLS\nX-User-Id / X-User-Role"| DPAuth1
    Router -->|"REST + mTLS"| DPAuth2
    DP1 -->|"Heartbeat (30s)"| Registry
    DP2 -->|"Heartbeat (30s)"| Registry
```

### Communication Protocol

| Direction | Mechanism | Authentication |
|-----------|-----------|----------------|
| User → Control Plane | HTTPS | JWT (Bearer token) |
| Control Plane → Data Plane | REST + optional mTLS | `X-DataPlane-Key` header |
| Data Plane → Control Plane | REST (registration + heartbeat) | `X-Internal-Key` header |
| User identity forwarding | HTTP headers | `X-User-Id` + `X-User-Role` |

### Key Components

| Component | Control Plane | Data Plane |
|-----------|--------------|------------|
| **Auth** | JWT validation (HS256/RS256 + JWKS) | API key from control plane |
| **Database** | Tenants, data planes, usage events | Chat history, sessions |
| **Routing** | Resolve tenant → data plane, streaming proxy | N/A (receives proxied requests) |
| **Rate Limiting** | Per-tenant sliding window (configurable RPM) | N/A (enforced at CP) |
| **Health** | Monitors data planes via heartbeat | Registers + sends heartbeats |
| **Chat UI** | Serves SPA at `/` | Not served (CP handles UI) |
| **AI Pipeline** | Not present | Full LangGraph agent pipeline |

### Service Directory Layout

```
services/
├── api/                    # Monolith (original, still works standalone)
├── control-plane/          # Control Plane service
│   ├── app/
│   │   ├── auth/           # JWT auth (local + JWKS)
│   │   ├── middleware/     # Per-tenant rate limiting
│   │   ├── models/         # Tenant, DataPlane, UsageEvent (SQLAlchemy)
│   │   ├── proxy/          # Streaming proxy, mTLS, tenant routing
│   │   ├── registry/       # Data plane health monitor
│   │   └── routes/         # Auth, tenants, data planes, proxy, usage, health
│   ├── main.py             # FastAPI app (port 8001)
│   └── Dockerfile
└── data-plane/             # Data Plane service
    ├── app/
    │   ├── auth/           # API key validation + user context
    │   ├── config.py       # Data plane settings
    │   ├── registration/   # Heartbeat loop to control plane
    │   └── routes/         # Chat, upload, health
    ├── main.py             # FastAPI app (port 8080)
    └── Dockerfile
```

---

## Related Docs

- [AWS Deployment](deployment-aws.md) — EKS provisioning, staging/prod, bootstrap, cost management
- [Azure Deployment](deployment-azure.md) — AKS provisioning, Workload Identity, Key Vault
- [API Reference & Chat UI](api-reference.md) — endpoints, streaming protocol, sample queries
- [Resolution Intelligence Architecture](resolution-intelligence-architecture.md) — support memory, trust gates, actions, and audit
- [Operations Guide](operations.md) — CI/CD, observability, testing, security, troubleshooting
- [Request Flow](request_flow.md) — detailed step-by-step query lifecycle (monolith + split modes)
- [Security](security.md) — security controls, mTLS, API key auth
- [Scaling](scaling.md) — autoscaling strategy, per-tenant data planes
- [Roadmap](ROADMAP.md) — enterprise features and zero trust roadmap
- [Enterprise Analytics Execution Plan](ENTERPRISE_ANALYTICS_EXECUTION_PLAN.md) — target architecture, delivery gates, workstreams, and model delegation rules
