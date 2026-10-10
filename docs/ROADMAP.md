# Product Roadmap

> This document tracks the original support/RAG platform roadmap. The
> catalog-neutral enterprise analytics program is maintained separately in
> [Enterprise Analytics Roadmap and Execution Plan](ENTERPRISE_ANALYTICS_EXECUTION_PLAN.md).
> Its next integrated agent-graph, ontology/context, harness, and evaluation
> program is maintained in the
> [Agentic Data Stack Execution Plan](AGENTIC_DATA_STACK_EXECUTION_PLAN.md).
> The OpenSearch migration, enterprise retrieval, personalization, and
> recommendation program is maintained in
> [Enterprise Search and Recommendation OpenSearch Execution Plan](ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md).
> The bounded LLM reasoning, grounded resolution, and typed action program is
> maintained in
> [LLM Search and Resolution Intelligence Execution Plan](LLM_RESOLUTION_INTELLIGENCE_EXECUTION_PLAN.md).
> The separate Roblox-like search, recommendation, and personalization vertical
> is maintained in the
> [Immersive Discovery Vertical Execution Plan](IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md).

## Current State (v1.0)

### What's Production-Ready

| Area | Status | Details |
|------|--------|---------|
| Multi-tenancy | Strong | Per-tenant isolation in Postgres, Qdrant, Neo4j, S3/Blob. Immutable TenantConfig. Rate limits per tenant. |
| Authentication | Strong | JWT with JWKS/IdP support (Auth0, Azure AD, Cognito). Tenant + user context injection. |
| Control Plane / Data Plane | Strong | SaaS-ready split architecture. CP handles auth, routing, rate limiting, admin. DP handles query processing in customer's region. mTLS + API key auth. 198 tests. |
| Testing | Strong | 198 tests across 3 suites — monolith (132), control plane (48), data plane (18). |
| CI/CD | Strong | Trunk-based: lint → test → build → staging (auto) → prod (manual approval). |
| Multi-cloud | Strong | AWS (EKS, Aurora, S3, ECR) and Azure (AKS, Postgres Flex, Blob, ACR) with provider abstraction. |
| Secrets | Strong | Azure Key Vault + ESO + Workload Identity. AWS Secrets Manager + IRSA. No static credentials on pods. |
| Observability | Good | OpenTelemetry with X-Ray, Azure Monitor, OTLP. Structured JSON logging. |
| Container security | Good | Non-root, drop ALL capabilities, multi-stage builds, 125MB API image. |
| API design | Good | v1 prefix, Pydantic validation, per-tenant rate limiting with 429 + Retry-After. |
| Documentation | Good | Architecture docs, request flow, security guide, CP/DP architecture, CONTRIBUTING.md. |

---

## Phase 1 — Security Hardening (Practical)

Priority: **High** | Effort: **1-2 days** | Blocks: production confidence

These are proportional security improvements — not full zero trust, which would be overkill at this stage.

### 1.1 TLS on Ingress
- [ ] Install cert-manager via Helm
- [ ] Create ClusterIssuer with Let's Encrypt
- [ ] Add TLS section to ingress template (`deploy/helm/api/templates/ingress.yaml`)
- [ ] Add HSTS annotation: `nginx.ingress.kubernetes.io/hsts: "true"`

### 1.2 CORS Lockdown
- [ ] Change `CORS_ORIGINS` default from `"*"` to empty string in `services/api/app/config.py`
- [ ] Set explicit allowed origins per environment in Helm values

### 1.3 API Pod NetworkPolicy
- [ ] Create `deploy/helm/api/templates/networkpolicy.yaml`
- [ ] Default deny all ingress/egress
- [ ] Allow ingress from ingress-nginx on port 8000
- [ ] Allow egress to Postgres (5432), Redis (6379/6380), Qdrant (6333/6334), Neo4j (7687)
- [ ] Allow egress to Key Vault / Secrets Manager endpoints (HTTPS 443)

### 1.4 Re-enable Access Logs
- [ ] Remove `logging.getLogger("uvicorn.access").disabled = True` from logging config
- [ ] Add request_id correlation to access log format

### 1.5 Encryption at Rest
- [ ] AWS: Add `storage_encrypted = true` to Aurora in `infra/terraform/rds.tf`
- [ ] AWS: Add `server_side_encryption_configuration` to S3 in `infra/terraform/s3.tf`
- [ ] Azure: Add `storage_mb` encryption settings to Postgres (enabled by default)
- [ ] Azure: Verify Blob Storage encryption (enabled by default, confirm CMK if needed)

---

## Phase 2 — Enterprise Features

Priority: **Critical for deals** | Effort: **2-3 weeks** | Blocks: enterprise sales

### 2.1 Admin API & Tenant Management
**Why:** Enterprises need self-service onboarding, not hardcoded tenant configs.

- [ ] Move tenant registry from static config to database table
- [ ] `POST /api/v1/admin/tenants` — create tenant with config (rate limits, quotas, features)
- [ ] `GET /api/v1/admin/tenants` — list all tenants with usage summary
- [ ] `PATCH /api/v1/admin/tenants/{id}` — update config, enable/disable
- [ ] `GET /api/v1/admin/tenants/{id}/usage` — queries, tokens, storage, active users
- [ ] Admin role check middleware (only `role=admin` can access `/admin/*`)
- [ ] Usage metering table — record per-request: tenant_id, user_id, tokens_in, tokens_out, timestamp

### 2.2 Data Governance (GDPR / SOC2)
**Why:** Deal-breaker for EU customers and any SOC2-audited buyer.

- [ ] `GET /api/v1/users/{id}/export` — export all user data as JSON (chat history, uploaded docs, feedback)
- [ ] `DELETE /api/v1/users/{id}/data` — cascade delete across Postgres, Qdrant, Neo4j, S3/Blob
- [ ] Configurable per-tenant data retention TTL on chat sessions
- [ ] Async cleanup job — purge expired sessions on schedule
- [ ] Audit log middleware — emit structured events: who accessed what resource, when, outcome
- [ ] Audit events stored in append-only table (or shipped to immutable log sink)

### 2.3 Database High Availability
**Why:** Required to commit to any uptime SLA (99.9%+).

- [ ] AWS: Uncomment second Aurora instance in `infra/terraform/rds.tf` (`two = {}`)
- [ ] AWS: Set Redis `num_cache_clusters = 2` in `infra/terraform/redis.tf`
- [ ] Azure: Set `zone_redundant = true` on Postgres Flexible Server
- [ ] Azure: Enable Redis geo-replication or zone redundancy
- [ ] Add PodDisruptionBudget to Helm chart (`minAvailable: 1`)
- [ ] Document RTO/RPO targets in `docs/disaster-recovery.md`

### 2.4 Python SDK
**Why:** Developers evaluate platforms by how fast they can integrate.

- [ ] Auto-generate typed client from OpenAPI spec (`openapi-python-client`)
- [ ] Package as `rag-platform-sdk` with retry logic, streaming support, typed responses
- [ ] Publish to private PyPI or Artifactory
- [ ] Include quickstart examples in SDK README
```python
from rag_platform import RAGClient

client = RAGClient(base_url="https://api.example.com", api_key="...")
response = client.chat("What does our policy say about remote work?")
print(response.answer)
```

### 2.5 Webhook / Event System
**Why:** Enterprise integrations are async — teams need to trigger downstream workflows.

- [ ] `POST /api/v1/webhooks` — register callback URL with event filter
- [ ] `GET /api/v1/webhooks` — list registered webhooks for tenant
- [ ] `DELETE /api/v1/webhooks/{id}` — unregister
- [ ] Event types: `document.ingested`, `document.failed`, `feedback.submitted`, `session.created`
- [ ] Async worker: poll events table, send HTTP POST to registered URLs with HMAC signature
- [ ] Retry with exponential backoff (3 attempts), dead letter after failure

---

## Phase 3 — SaaS Data Connectors (Ingestion Framework)

Priority: **High** | Effort: **2-3 weeks** | Blocks: enterprise data sources

> **Decision:** Use **Airbyte (PyAirbyte)** for SaaS connector layer — not custom connectors.
> Custom connectors for 10+ SaaS apps would be a full-time maintenance burden.
> LlamaHub loaders lack incremental sync and managed auth for production use.

### Current State

The ingestion pipeline only supports **file-based** ingestion:
- S3/Azure Blob uploads → Ray pipeline → Parse → Chunk → Embed → Index (Qdrant + Neo4j)
- Formats: PDF, DOCX, HTML, TXT/MD
- No SaaS API integration (Confluence, Slack, Jira, Google Drive, etc.)

### Architecture: Airbyte + Existing Ray Pipeline

```
Tenant Admin UI: "Connect your Confluence"
        │
        ▼
┌─────────────────────────────────────────┐
│  Airbyte (PyAirbyte)                    │
│  ┌───────────┐ ┌───────────┐ ┌───────┐ │
│  │ Confluence│ │ Google    │ │ Slack │ │
│  │ Connector │ │ Drive     │ │       │ │
│  └─────┬─────┘ └─────┬─────┘ └───┬───┘ │
│        │ OAuth + incremental sync │     │
│        └──────────┬───────────────┘     │
│                   ▼                     │
│         Raw JSON / Documents            │
└───────────────────┬─────────────────────┘
                    ▼
         S3 / Azure Blob (staging)
         uploads/{tenant_id}/saas/{source}/{doc_id}
                    │
                    ▼ (existing pipeline — no changes needed)
┌──────────────────────────────────────────┐
│  Ray Ingestion Pipeline                  │
│  Parse → Chunk → Embed → Index           │
│  (Qdrant vectors + Neo4j graph)          │
└──────────────────────────────────────────┘
```

### Why Airbyte

| Requirement | Airbyte | Custom connectors | LlamaHub |
|---|---|---|---|
| SaaS connectors | 550+ (Confluence, Slack, Jira, Google Drive, SharePoint, Salesforce, Notion, HubSpot) | Build each one | 300+ but not production-grade |
| OAuth management | Built-in per connector | You build it per SaaS | You manage tokens manually |
| Incremental sync | Native cursor-based with state | You build state tracking | Not supported |
| Rate limiting | Handled per connector | You implement per API | Basic / inconsistent |
| Python integration | PyAirbyte — outputs DataFrames, streams to S3 | Native Python | Native Python |
| Maintenance | Airbyte-managed connectors updated by vendor | You fix every API change | Community-maintained, variable quality |
| License | Elastic License 2.0 (self-hostable) | N/A | MIT |
| Cost | Free self-hosted, paid cloud | Engineering time (3-4x underestimated) | Free |

### Implementation Plan

#### 3.1 Connector Infrastructure
- [ ] Add `pyairbyte` to `requirements-ingestion.txt`
- [ ] Create `pipelines/ingestion/connectors/` module
- [ ] Create `pipelines/ingestion/connectors/base.py` — `SaaSConnector` protocol:
  ```python
  class SaaSConnector(Protocol):
      def sync(self, tenant_id: str, config: dict) -> Iterator[Document]: ...
      def get_state(self, tenant_id: str) -> dict: ...
      def set_state(self, tenant_id: str, state: dict) -> None: ...
  ```
- [ ] Create `pipelines/ingestion/connectors/airbyte_adapter.py` — wraps PyAirbyte:
  - Accepts source name + config (e.g., `source-confluence`, `{"domain": "...", "api_token": "..."}`)
  - Handles incremental sync via Airbyte state management
  - Writes raw docs to S3/Blob staging path: `uploads/{tenant_id}/saas/{source}/{doc_id}`
  - Triggers existing Ray ingestion pipeline on new files

#### 3.2 Connector Configuration (per-tenant)
- [ ] Add `tenant_connectors` table in Postgres:
  ```sql
  CREATE TABLE tenant_connectors (
      id UUID PRIMARY KEY,
      tenant_id VARCHAR NOT NULL,
      source_type VARCHAR NOT NULL,     -- 'confluence', 'google_drive', 'slack'
      config JSONB NOT NULL,            -- source-specific config (encrypted)
      sync_state JSONB DEFAULT '{}',    -- Airbyte incremental sync cursor
      schedule VARCHAR DEFAULT 'hourly', -- 'hourly', 'daily', 'manual'
      enabled BOOLEAN DEFAULT TRUE,
      last_sync_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- [ ] Store connector credentials in Key Vault / Secrets Manager (not in DB)
- [ ] Reference secrets by Key Vault secret name in `config` JSONB

#### 3.3 Admin API for Connectors
- [ ] `POST /api/v1/admin/connectors` — register a SaaS connector for tenant
- [ ] `GET /api/v1/admin/connectors` — list connectors for tenant
- [ ] `PATCH /api/v1/admin/connectors/{id}` — update config, schedule, enable/disable
- [ ] `POST /api/v1/admin/connectors/{id}/sync` — trigger manual sync
- [ ] `GET /api/v1/admin/connectors/{id}/status` — last sync time, docs synced, errors

#### 3.4 Sync Scheduler
- [ ] Cron-based sync worker (Ray job or K8s CronJob):
  - Query `tenant_connectors` where `enabled = true` and schedule matches
  - Run Airbyte sync per connector
  - Write new docs to S3/Blob staging
  - Trigger Ray ingestion pipeline
  - Update `sync_state` and `last_sync_at`
- [ ] Webhook option: receive push events from SaaS apps (Confluence webhooks, Google Drive push notifications)

#### 3.5 Priority Connectors (Phase 1)
- [ ] **Confluence** — most requested for enterprise knowledge bases
- [ ] **Google Drive** — docs, sheets, slides
- [ ] **SharePoint / OneDrive** — Microsoft shops
- [ ] **Notion** — popular for product/engineering docs
- [ ] **Slack** — channel history for support/ops knowledge

#### 3.6 Priority Connectors (Phase 2)
- [ ] Jira (issue context for support RAG)
- [ ] Salesforce (CRM knowledge)
- [ ] HubSpot (marketing content)
- [ ] GitHub (README, wiki, issues, PRs)
- [ ] Zendesk (support tickets)

### Alternatives Considered

| Option | Verdict |
|---|---|
| **Custom connectors** | Rejected — 2-4 weeks per connector to build, ongoing maintenance as APIs change. Doesn't scale past 3-5 sources. |
| **LlamaHub loaders** | Rejected for production — no incremental sync, no managed auth, inconsistent quality. Good for prototyping only. |
| **Fivetran** | Rejected — warehouse-first model requires secondary pipeline for RAG. $10K-500K/yr. Overkill. |
| **Nango** | Considered for future — best-in-class OAuth management for 700+ APIs. Could complement Airbyte if we need user-facing "Connect your app" UI with white-label OAuth flows. |
| **Vectorize.io / Ragie.ai** | Rejected — managed RAG platforms that would replace our entire pipeline. We want control. |
| **Unstructured.io connectors** | Already in the pipeline for doc parsing. Only 30 connectors — Airbyte covers far more SaaS apps. |

---

## Phase 4 — Operational Maturity

Priority: **Medium** | Effort: **1-2 weeks** | Blocks: scale

### 3.1 Backup & Disaster Recovery
- [ ] Enable cross-region read replica for Aurora (warm standby)
- [ ] Enable Azure Postgres geo-redundant backup
- [ ] Automated backup restoration tests (weekly cron, verify integrity)
- [ ] Document failover runbook in `docs/disaster-recovery.md`
- [ ] S3/Blob cross-region replication for document storage

### 3.2 Observability Dashboards & Alerting
- [ ] Grafana dashboards: request latency (p50/p95/p99), error rate, active sessions per tenant
- [ ] Alert rules: error rate > 5%, latency p99 > 2s, pod restarts > 3 in 10min
- [ ] Business metrics: queries/day per tenant, token usage, cache hit rate
- [ ] On-call runbook for each alert

### 3.3 Load Testing
- [ ] k6 or Locust test suite simulating concurrent tenants
- [ ] Scenarios: sustained load, spike, long-running sessions
- [ ] Integrate into CI as nightly job (not blocking PRs)
- [ ] Document capacity limits (max concurrent users per pod, max throughput)

### 3.4 API Pagination & Versioning
- [ ] Add cursor-based pagination to chat history (`GET /api/v1/sessions?cursor=...&limit=20`)
- [ ] Add pagination to admin endpoints
- [ ] Document API deprecation policy (min 6 months notice)
- [ ] Support `Accept-Version` header for future breaking changes

---

## Phase 5 — Search Quality

Priority: **Medium** | Effort: **1-2 weeks** | Blocks: accuracy

### 5.1 Reranking
- [ ] Add cross-encoder reranking stage after vector retrieval
- [ ] Configurable per tenant (enable/disable, model choice)
- [ ] Compare retrieval quality with/without reranking via eval suite

### 5.2 Evaluation in CI
- [ ] Integrate Ragas eval suite (`eval/ragas/run.py`) into CI pipeline
- [ ] Maintain golden dataset of Q&A pairs per tenant
- [ ] Block deploys if faithfulness or relevancy drops below threshold
- [ ] Track eval scores over time (regression detection)

### 5.3 Feedback Loop
- [ ] Aggregate user feedback (thumbs up/down) per query pattern
- [ ] Surface low-scoring queries in admin dashboard
- [ ] Use negative feedback to improve retrieval (hard negative mining)

---

## Phase 6 — Zero Trust Architecture

Priority: **Low (unless compliance requires it)** | Effort: **3-4 weeks**

> **When to implement:** Only when compliance frameworks (SOC2 Type II, HIPAA, FedRAMP) or
> customer contracts explicitly require it. The security hardening in Phase 1 is sufficient
> for most enterprise deployments.

### 6.1 Service Mesh (mTLS)
- [ ] Deploy Istio or Linkerd to cluster
- [ ] Enable automatic mTLS for all pod-to-pod communication
- [ ] Configure strict PeerAuthentication (reject plaintext)
- [ ] Authorization policies: API → allowed backends only

### 6.2 Fine-Grained RBAC Enforcement
- [ ] Create `app/middleware/rbac.py` — evaluate `permissions` claim from JWT per endpoint
- [ ] Define permission matrix: `chat:read`, `chat:write`, `admin:read`, `admin:write`, `docs:upload`
- [ ] Route decorator: `@requires_permission("chat:write")`
- [ ] Return 403 with specific missing permission in error response

### 6.3 Secrets Rotation
- [ ] Key Vault rotation policy (90-day auto-rotate for DB passwords)
- [ ] Short-lived database credentials via Postgres Managed Identity (Azure) or IAM auth (AWS)
- [ ] JWT token refresh endpoint with sliding window
- [ ] Token revocation via Redis blacklist (check on every request)

### 6.4 Admission Control & Policy Enforcement
- [ ] Deploy OPA Gatekeeper or Kyverno
- [ ] Policies: only allow images from ACR/ECR, enforce resource limits, block privileged pods
- [ ] Pod Security Standards: enforce `restricted` profile via namespace labels
- [ ] Image signing with cosign in CI, verification in admission webhook

### 6.5 Network Microsegmentation
- [ ] NetworkPolicy per service (not just API — also Qdrant, Neo4j, Ray, Redis)
- [ ] Deny all by default, explicit allow per service dependency
- [ ] Separate namespaces: `rag-api`, `rag-data`, `rag-compute` with cross-namespace policies
- [ ] Egress policies: restrict outbound to known endpoints only

### 6.6 Comprehensive Audit Trail
- [ ] Audit every API call: user, tenant, action, resource, outcome, IP, timestamp
- [ ] Audit secret access via Key Vault diagnostic settings / CloudTrail
- [ ] Ship audit logs to immutable storage (S3 Glacier / Blob Archive with legal hold)
- [ ] Retention: 7 years for compliance, queryable via Athena / Log Analytics

### 6.7 WAF & DDoS Protection
- [ ] AWS: AWS WAF in front of ALB with managed rule groups (core, SQL injection, known bad inputs)
- [ ] Azure: Azure Front Door with WAF policy
- [ ] Per-user/per-tenant rate limiting (replace IP-only limiting)
- [ ] Geographic blocking if required by data residency

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-08 | Trunk-based development | Simpler than GitFlow for small team, faster feedback loop |
| 2026-03-08 | Skip full zero trust | Overkill for current stage — Phase 1 hardening is proportional to actual risk |
| 2026-03-08 | Prioritize admin API + GDPR over SDK | Unblocks procurement; SDK unblocks developer adoption (later) |
| 2026-03-08 | Single-region with backups | Cross-region DR deferred until SLA commitments require it |
| 2026-03-08 | Airbyte (PyAirbyte) for SaaS connectors | 550+ connectors with managed auth + incremental sync. Custom connectors don't scale past 3-5 sources. LlamaHub not production-grade. |
| 2026-03-09 | Control Plane / Data Plane split | Enables SaaS deployment with data residency. CP manages auth/routing/admin. DP runs in customer's cloud. REST + mTLS communication. Per-tenant rate limiting. |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-08 | Initial roadmap — security hardening, enterprise features, zero trust analysis |
| 1.1 | 2026-03-08 | Add Phase 3 — SaaS data connectors via Airbyte (PyAirbyte) integration design |
| 1.2 | 2026-03-09 | Control Plane / Data Plane architecture implemented. 198 tests (132 monolith + 48 CP + 18 DP). Updated docs. |
