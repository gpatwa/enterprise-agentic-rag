# Enterprise Search and Recommendation OpenSearch Execution Plan

Status: Local implementation through OS-088 complete; production sign-off remains conditional on live evidence

Current implementation checkpoint (2026-08-23): OS-001 through OS-035 are merged;
OS-036 provides a separate search worker deployable, OS-037 provides checkpointed
backfill and dry-run commands, OS-038 provides bounded source/index reconciliation,
OS-039 gates generation alias swaps on reconciliation results, OS-040 provides an
allowlisted tenant/ACL filter compiler, OS-041 provides scoped BM25 lexical
retrieval with exact-ID and phrase boosts, and OS-042 through OS-048 provide
filtered vector retrieval, deterministic hybrid RRF, stable lexical pagination,
bounded provider orchestration, and an opt-in support integration. OS-070
through OS-079 add consented interaction events, deterministic feature
materialization, policy-aware reranking, recommendation metrics, and guarded
experiments. OS-080 through OS-088 add adversarial isolation tests, redacted
audit evidence, retention/deletion helpers, SLO definitions, backup/restore
drills, capacity guidance, and the conditional production review record. Local
OpenSearch 2.15 integration evidence is complete: 24 fixture documents,
12-query evaluation, zero ACL leaks, and alias rollback verification. Production
TLS, provider-managed snapshots, and human production sign-off remain external
evidence gates.
Audience: Engineering leads, reviewers, and delegated coding models
Scope: Agentic Search and Support Resolution Intelligence under `services/api`,
`apps/support-web`, and their deployment assets

The dependent LLM reasoning, grounded synthesis, and typed action work is
maintained separately in the
[LLM Search and Resolution Intelligence Execution Plan](LLM_RESOLUTION_INTELLIGENCE_EXECUTION_PLAN.md).

## 1. Executive Decision

Use OpenSearch as the enterprise search plane for lexical, vector, hybrid,
filtered, personalized, and recommendation-candidate retrieval.

PostgreSQL and object storage remain authoritative. OpenSearch is a rebuildable,
derived index. Neo4j remains the relationship and knowledge-graph store.
Qdrant is retained only as a temporary local/demo fixture while the OpenSearch
path is built. There is no customer-facing backward-compatibility promise and
no requirement to preserve Qdrant as a production fallback.

This is a pre-customer greenfield launch. Breaking API, mapping, persistence,
and provider changes are allowed when they improve the target architecture.
Operational recovery still requires idempotency, auditability, fail-closed
authorization, and alias rollback for incomplete or failed index operations.

Do not place OpenSearch-specific types in support domain models. All product
code must depend on a versioned search contract so the backend remains
replaceable.

## 2. Product Outcome

An authorized enterprise user can search tickets, comments, articles, files,
and approved business context with exact-term and semantic recall. Results are
permission-trimmed, tenant-scoped, explainable, and suitable for an agent to use
as evidence. The same retrieval platform can generate personalized and
recommendation candidates without becoming the system of record for customer
data or behavioral events.

The first production release succeeds when it can:

- Return exact identifiers, error strings, product names, and phrases through
  BM25 retrieval.
- Return semantically related content through vector retrieval.
- Fuse lexical and vector candidates deterministically.
- Apply tenant and document ACL filters before scoring results.
- Preserve source, model, schema, permission, and index versions in every trace.
- Rebuild an index from canonical data without losing authoritative state.
- Compare against the existing Qdrant plus lexical implementation offline while
  building confidence in the new path.
- Produce recommendation candidates using explicit behavioral and business
  signals without leaking one tenant's activity into another tenant.

## 3. Current Baseline

Available now:

- Qdrant vector indexing and retrieval behind `VectorDBClient`.
- A dependency-light Python BM25-style support search implementation.
- Reciprocal-rank fusion of vector and lexical results.
- Canonical support tickets, comments, articles, durable jobs, and audit events.
- Mandatory tenant filters in the support search path.
- PostgreSQL, Redis, Qdrant, Neo4j, S3/Blob, Docker Compose, Helm, and Terraform.

Production gaps:

- Lexical search loads a bounded candidate set into the API process and ranks it
  in Python. It is suitable for demos, not enterprise corpus scale.
- The vector contract cannot express text queries, hybrid ranking, ACL scopes,
  aggregations, index versions, or ranking explanations.
- Index writes are coupled to application workflows rather than a durable
  outbox with replay and reconciliation.
- There is no OpenSearch client, mapping, index lifecycle, alias, deployment,
  benchmark, or runbook.
- Personalization and recommendation events, features, policies, and evaluation
  are not yet product contracts.

## 4. Target Architecture

```text
Canonical sources
  PostgreSQL + S3/ADLS + SaaS connectors
                    |
                    v
        Durable search outbox
                    |
                    v
       Search indexing worker
         |                 |
         v                 v
  OpenSearch index     Neo4j graph
  BM25 + vectors       relationships
         |                 |
         +--------+--------+
                  v
        EnterpriseSearchProvider
        scope + query + evidence
                  |
                  v
     ranking / personalization policy
                  |
                  v
      LangGraph agent and support UI
```

### System-of-record boundaries

| Concern | Authoritative source |
|---|---|
| Tickets, comments, articles, users, actions | PostgreSQL/source helpdesk |
| Raw files and lake objects | S3, ADLS, or customer lake |
| Embeddings and searchable fields | Rebuildable OpenSearch index |
| Relationship graph | Neo4j, rebuildable from canonical records |
| User/group identity | Customer identity provider |
| Document permission assignments | Source system and normalized ACL record |
| Search and interaction events | PostgreSQL event store initially |
| Derived popularity/profile features | Versioned feature materialization |
| Search audit evidence | Append-only Compass audit store |

### Required search contract

Every query must include a `SearchScope` containing:

- `tenant_id` with no production default.
- `principal_id` and normalized group or ACL tokens.
- `purpose` and product surface.
- Optional provider, status, source type, time, and classification filters.

Every result must include:

- Stable document and source identifiers.
- Normalized score plus lexical, vector, and fusion components when available.
- Source URI, title, text excerpt, and metadata.
- Retrieval method and ranking explanation summary.
- Index schema, embedding model, content, and permission versions.

### Index topology

- Use one versioned physical index per product domain and schema generation.
- Point a stable read alias and write alias to the active generation.
- Use mandatory `tenant_id` and `acl_tokens` fields in shared indexes.
- Allow a tenant registry to route regulated or very large tenants to dedicated
  indexes without changing the query contract.
- Never create one index per tenant by default; uncontrolled shard growth is an
  operational failure mode.

## 5. Architectural Constraints

1. Fail closed when tenant or ACL scope is missing or malformed.
2. Use an outbox and idempotent worker; do not rely on request-path dual writes.
3. Keep provider payloads out of API response contracts.
4. Version mappings, embeddings, analyzers, ranking configuration, and features.
5. Use aliases for zero-downtime reindex and operational rollback.
6. Redact or exclude prohibited content before indexing.
7. Keep recommendation behavior events out of document payloads unless a
   reviewed feature contract explicitly materializes them.
8. OpenSearch is first-stage retrieval. Business policy and final reranking stay
   in Compass.
9. Qdrant retirement is an implementation decision, not a customer compatibility gate.
10. No analytics product imports. Shared primitives belong in
    `packages/platform_contracts` only when both products actually consume them.

## 6. Delivery Gates

| Gate | Exit evidence |
|---|---|
| G0: Contract | Provider-neutral models, fake provider, and conformance tests pass |
| G1: Index | Versioned mapping, aliases, outbox, worker, replay, and delete paths pass |
| G2: Retrieval | BM25, vector, hybrid, ACL, filters, and explanations pass golden tests |
| G3: Relevance baseline | Offline Qdrant/OpenSearch comparison establishes recall, ranking, ACL, and latency evidence |
| G4: Canary | Isolation, relevance, p95 latency, failure, and rollback gates pass |
| G5: Personalization | Event, feature, policy, candidate, and evaluation contracts pass |
| G6: Production | SLO, DR, security, cost, operations, and customer acceptance pass |

## 7. Atomic Execution Tasks

Each task is intended for one lower-capability coding model in one fresh
worktree. A task must not be combined with another task unless the dispatch
table explicitly says it shares ownership.

### A. Decisions, contracts, and evaluation baseline

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| OS-001 | Record the OpenSearch architecture decision and alternatives | `docs/adr/ADR-OS-001-opensearch-enterprise-search.md` | None | ADR states authority boundaries, Qdrant migration, Azure/AWS hosting options, and stop conditions |
| OS-002 | Define immutable search request, scope, filter, result, and explanation models | New `services/api/app/search/models.py` | OS-001 | Serialization and invalid-scope tests pass; no OpenSearch imports |
| OS-003 | Define async `EnterpriseSearchProvider` protocol | New `services/api/app/search/base.py` | OS-002 | Runtime protocol test covers lifecycle, index, write, delete, and query methods |
| OS-004 | Add an in-memory fake provider for contract tests only | New `services/api/tests/fakes/search_provider.py` | OS-003 | Fake passes conformance tests and has deterministic ordering |
| OS-005 | Freeze a support-search golden corpus and judgments | New `services/api/tests/fixtures/search/` | None | Corpus includes IDs, errors, synonyms, ACL conflicts, stale docs, and semantic matches |
| OS-006 | Add backend-neutral relevance metrics | New `services/api/app/search/evaluation.py`, targeted tests | OS-005 | Recall@K, MRR, and nDCG calculations pass hand-computed fixtures |
| OS-007 | Add the conformance and golden evaluation test harness | New `services/api/tests/test_enterprise_search_contract.py` | OS-004, OS-006 | Fake provider report is deterministic and machine-readable |

### B. OpenSearch provider foundation

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| OS-010 | Add optional OpenSearch dependency with an explicit compatible range | `services/api/requirements.txt` | OS-001 | Clean API dependency install succeeds |
| OS-011 | Add OpenSearch endpoint, auth, TLS, timeout, and pool settings | `services/api/app/config.py`, config tests only | OS-001 | Dev and production validation tests fail on unsafe/missing production settings |
| OS-012 | Add enterprise search provider factory with lazy OpenSearch selection | New `services/api/app/search/factory.py`, `services/api/tests/test_search_provider_factory.py` | OS-003, OS-011 | Unknown providers fail clearly; imports remain lazy; no customer compatibility adapter is introduced |
| OS-013 | Implement async connection lifecycle and health check | New `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_provider.py` | OS-010 to OS-012 | Mocked client tests cover connect, close, healthy, auth failure, and timeout |
| OS-014 | Normalize OpenSearch exceptions and retryability | `services/api/app/search/errors.py`, `services/api/tests/test_opensearch_provider.py` | OS-013 | Auth, mapping, throttling, timeout, and unavailable errors map deterministically |
| OS-015 | Add bounded retry, backoff, and circuit-breaker hooks | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_provider.py` | OS-014 | Nonretryable errors run once; retryable errors stop at configured bound |

### C. Mapping and index lifecycle

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| OS-020 | Define versioned support document schema | New `services/api/app/search/schema.py` | OS-002 | Schema includes tenant, ACL, source, content, timestamps, vectors, versions, and rank features |
| OS-021 | Build deterministic OpenSearch settings and mappings | New `services/api/app/search/mappings.py` | OS-020 | Snapshot test covers analyzers, keyword subfields, date fields, vector dimensions, and disabled dynamic mapping |
| OS-022 | Implement physical index creation | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_provider.py` | OS-013, OS-021 | Create is idempotent; incompatible existing mapping fails with actionable error |
| OS-023 | Implement read/write alias creation and atomic swap | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_provider.py` | OS-022 | Test proves swap and rollback without changing callers |
| OS-024 | Implement index metadata inspection | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_provider.py` | OS-022 | Health returns generation, mapping, model, document count, and alias state |
| OS-025 | Add mapping compatibility checker | New `services/api/app/search/compatibility.py` | OS-021, OS-024 | Additive and breaking mapping cases are classified correctly |

### D. Durable indexing and reconciliation

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| OS-030 | Define search outbox and checkpoint persistence models | `services/api/app/support/models.py`, new migration | OS-020 | Migration up/down test and unique idempotency key pass |
| OS-031 | Emit outbox events from canonical support writes | `services/api/app/support/store.py`, tests | OS-030 | Create, update, permission change, and delete events commit atomically with source records |
| OS-032 | Define canonical support-to-search document mapper | New `services/api/app/search/support_mapper.py` | OS-020 | Golden mapper tests cover tickets, comments, articles, chunks, nulls, and redaction |
| OS-033 | Implement OpenSearch bulk upsert | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_provider.py` | OS-013, OS-022, OS-032 | Partial failures are reported per document and successful writes are not replayed unnecessarily |
| OS-034 | Implement delete and tombstone processing | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_provider.py` | OS-033 | Tenant-scoped delete cannot affect another tenant; replay is idempotent |
| OS-035 | Add bounded indexing worker loop | New `services/api/app/search/worker.py` | OS-030, OS-033, OS-034 | Claim, lease, retry, dead-letter, and shutdown tests pass |
| OS-036 | Wire worker startup as a separate deployable process | New entry point, Docker/Helm worker wiring only | OS-035 | API request path does not run indexing work; readiness reflects dependencies |
| OS-037 | Add backfill command with checkpoints and dry run | New `services/api/app/search/backfill.py` | OS-032, OS-035 | Interrupted backfill resumes without duplicate documents |
| OS-038 | Add source/index reconciliation report | New `services/api/app/search/reconcile.py` | OS-037 | Missing, extra, stale, ACL-mismatched, and version-mismatched counts are reported |
| OS-039 | Add reindex command using new generation and alias swap | New `services/api/app/search/reindex.py` | OS-023, OS-037, OS-038 | Reindex refuses alias swap until reconciliation threshold passes |

### E. Query behavior

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| OS-040 | Build fail-closed tenant and ACL filter compiler | New `services/api/app/search/filters.py` | OS-002 | Missing scope raises; adversarial AND/OR/filter tests cannot broaden access |
| OS-041 | Implement BM25 lexical query | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_queries.py` | OS-013, OS-021, OS-040 | Golden exact-ID, error, phrase, title boost, status, and source tests pass |
| OS-042 | Implement filtered vector query | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_queries.py` | OS-013, OS-021, OS-040 | Correct distance, dimensions, threshold, tenant, and ACL behavior pass |
| OS-043 | Implement hybrid query and deterministic RRF | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_queries.py` | OS-041, OS-042 | Golden ordering and score components match expected values |
| OS-044 | Normalize highlights and ranking explanation | `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_queries.py` | OS-041 to OS-043 | Response contains no raw backend payload and preserves evidence versions |
| OS-045 | Add pagination contract using stable search-after tokens | `services/api/app/search/models.py`, `services/api/app/search/opensearch.py`, `services/api/tests/test_opensearch_queries.py` | OS-043 | Duplicate/missing result tests pass across multiple pages |
| OS-046 | Add timeout, cancellation, fallback, and circuit-breaker behavior | New `services/api/app/search/service.py`, `services/api/tests/test_search_service.py` | OS-015, OS-043 | Timeout does not leak partial unauthorized data; fallback is observable |
| OS-047 | Adapt support search to `EnterpriseSearchProvider` | `services/api/app/support/indexer.py`, `services/api/tests/test_support_indexing.py` | OS-043, OS-046 | Support search is migrated to the target contract; no legacy provider compatibility is required |
| OS-048 | Retire the legacy Qdrant search path after local OpenSearch validation | Removal/update of legacy support search wiring and targeted tests | OS-047, OS-050 | OpenSearch is the only supported enterprise path; local demo validation passes before removal |

### F. Local, cloud, and migration rollout

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| OS-050 | Add opt-in local OpenSearch Compose profile | `docker-compose.yml`, local runbook | OS-013, OS-022 | Profile starts healthy without changing default Qdrant demo |
| OS-051 | Add local integration test marker and fixtures | `services/api/tests/test_opensearch_integration.py`, minimal test configuration | OS-050 | Unit suite remains service-free; integration suite skips clearly when unavailable |
| OS-052 | Add OpenSearch Helm configuration and secrets contract | `deploy/helm/api/` only | OS-011, OS-036 | Helm lint and rendered security-context tests pass |
| OS-053 | Record Azure and AWS deployment selection ADR | New ADR only | OS-001 | ADR compares managed AWS, Azure-operated/BYOC, residency, upgrades, backups, and cost |
| OS-054 | Add selected cloud infrastructure module | Dedicated Terraform module only | OS-052, OS-053 | Format/validate pass; no deployment is performed by this task |
| OS-055 | Add shadow-query mode | New `services/api/app/search/shadow.py`, config, tests | OS-047, OS-048 | User receives primary result only; comparison cannot increase request failure rate |
| OS-056 | Add shadow comparison telemetry | Shadow module, tracing tests | OS-055 | Logs/metrics include overlap, rank deltas, latency, errors, and no raw sensitive text |
| OS-057 | Run offline relevance and ACL benchmark | Evaluation fixtures and a versioned report only | OS-007, OS-043, OS-051 | Report includes Qdrant+lexical and OpenSearch baselines |
| OS-058 | Add load, cold-cache, indexing, and failure tests | New load-test assets only | OS-051, OS-056 | Report captures p50/p95/p99, throughput, recovery, and filter recall |
| OS-059 | Add canary percentage and instant rollback controls | Config, routing module, tests | OS-055 to OS-058 | Deterministic tenant routing and rollback tests pass |
| OS-060 | Cut over one design-partner pilot after G4 approval | Configuration and release record only | OS-059, OS-080, OS-082, OS-084, and human approval | OpenSearch is primary for the pilot; alias and index-generation rollback evidence is available |

### G. Personalization and recommendation

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| OS-070 | Define versioned search interaction event model | New `services/api/app/search/events.py` | OS-002 | Search, click, open, accept, dismiss, resolve, and feedback events validate |
| OS-071 | Persist interaction events with consent and retention fields | New persistence model/migration and tests | OS-070 | Tenant, principal/pseudonym, purpose, consent, expiry, and idempotency are required |
| OS-072 | Capture events from support workflows | Support routes/workflow tests only | OS-071 | Events never block the user request and preserve correlation IDs |
| OS-073 | Define versioned ranking feature contract | New `services/api/app/search/features.py` | OS-070 | Recency, popularity, expertise, role, and content-quality features have defaults and provenance |
| OS-074 | Add offline feature materialization job | New job module and tests | OS-071, OS-073 | Rebuild is deterministic and tenant-scoped; expired data is excluded |
| OS-075 | Add policy-aware personalized reranker | New `services/api/app/search/ranking.py` | OS-043, OS-073 | ACL filtering precedes reranking; zero-history users receive deterministic baseline |
| OS-076 | Add similar-ticket/article candidate API | Search route and tests | OS-043 | Explanations identify similarity and policy filters; cross-tenant tests fail closed |
| OS-077 | Add support next-best-resolution candidates | Support workflow and tests | OS-075, OS-076 | Recommendations cite evidence and never execute actions automatically |
| OS-078 | Add recommendation evaluation metrics | Evaluation module and fixtures | OS-075 to OS-077 | Precision@K, Recall@K, coverage, novelty, and acceptance metrics are reproducible |
| OS-079 | Add guarded experiment assignment | New experiment module and tests | OS-078 | Stable assignment, exclusions, exposure logging, and kill switch pass |

### H. Enterprise trust and operations

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| OS-080 | Add exhaustive tenant and ACL isolation suite | New security tests only | OS-040, OS-047 | Shared and dedicated index paths fail closed under adversarial cases |
| OS-081 | Add TLS, credential rotation, and least-privilege runbook | Security/deployment docs only | OS-052 to OS-054 | Reviewer can rotate credentials without reindexing or downtime |
| OS-082 | Add audit evidence for index and query operations | Audit integration and tests | OS-035, OS-047 | Actor, tenant, operation, versions, result count, and outcome are recorded without query content leakage |
| OS-083 | Add deletion, retention, legal hold, and reindex behavior | Privacy routes/jobs and tests | OS-034, OS-038 | Erasure completes across canonical, index, backups policy, and reconciliation evidence |
| OS-084 | Define search SLIs, SLOs, dashboards, and alerts | Observability config/docs only | OS-056, OS-058 | Alerts cover availability, p95, errors, indexing lag, stale aliases, and ACL failures |
| OS-085 | Add backup, restore, and full rebuild drill | Operations scripts/docs only | OS-038, OS-039, OS-054 | Timed drill records RPO/RTO and validates document and permission counts |
| OS-086 | Add capacity and cost model | `docs/cost_model.md` or dedicated search cost doc | OS-058 | Model covers documents, vectors, shards, replicas, ingest, query, storage, and egress |
| OS-087 | Add production operations runbook | New `docs/runbooks/opensearch-operations.md` | OS-084 to OS-086 | On-call paths cover red/yellow cluster, throttling, mapping rejection, lag, reindex, and rollback |
| OS-088 | Complete security and production readiness review | Review record only | OS-080 to OS-087 | No open critical/high issue; product, security, and operations sign off |
| OS-089 | Decide Qdrant retention or retirement | New ADR only | OS-060, OS-088, 30 days evidence | ADR uses measured reliability, relevance, cost, and rollback data |

## 8. Dispatch Waves

| Wave | Tasks that may run in parallel | Required merge order |
|---|---|---|
| 0 | OS-001, OS-005 | Merge both before contract implementation |
| 1 | OS-002 then OS-003; OS-006 independently | OS-002 -> OS-003 -> OS-004 -> OS-007 |
| 2 | OS-010, OS-011, OS-020 | Merge config/dependency/schema before provider work |
| 3 | OS-012 to OS-015 sequential; OS-021 independently | Provider foundation before index lifecycle |
| 4 | OS-022 to OS-025 sequential; OS-030 and OS-032 parallel | Mapping/lifecycle before writes |
| 5 | OS-031; OS-033 and OS-040 parallel | Merge persistence before worker; filters before queries |
| 6 | OS-034 to OS-039 mostly sequential | Finish durable indexing and reindex gate |
| 7 | OS-041, OS-042, and OS-048 parallel | Merge OS-041 and OS-042 before OS-043; merge OS-048 before OS-047 |
| 8 | OS-050, OS-052, OS-053, OS-055 | Merge local/cloud docs before infrastructure or shadow tests |
| 9 | OS-051, OS-054, OS-056 to OS-059 | OS-060 also waits for OS-080, OS-082, OS-084, and human approval |
| 10 | OS-070, OS-073 | Event and feature contracts before all recommendation tasks |
| 11 | OS-071, OS-074, OS-076 | Merge before capture/ranking/workflow tasks |
| 12 | OS-072, OS-075, OS-078 | Merge before OS-077 and OS-079 |
| 13 | OS-080 to OS-087 by non-overlapping ownership | OS-088 after all production evidence |
| 14 | OS-089 | At least 30 days after enterprise cutover |

## 9. Delegation Rules

Give a delegated model exactly one task ID and this plan. Require it to:

1. Read the task, dependencies, owned files, and directly related existing code.
2. Stop if a dependency is missing from its branch.
3. Modify only owned files plus the smallest necessary import/export file.
4. Follow the target contract; breaking changes are allowed before customer launch.
5. Add focused tests before reporting completion.
6. Run the targeted tests, API suite, and `git diff --check`.
7. Commit with `feat(search): OS-NNN short description` or the appropriate
   `test`, `docs`, `fix`, or `chore` type.
8. Report changed files, tests, assumptions, and unresolved risks.

Delegated models must not:

- Deploy cloud resources.
- Change production traffic or defaults.
- Remove Qdrant or Python lexical fallback except in the explicit retirement task.
- Weaken tenant, ACL, TLS, authentication, or audit behavior.
- Add Elasticsearch clients or Elastic-specific APIs.
- Introduce a second task's deliverable opportunistically.
- Reformat unrelated files or edit analytics product code.

## 10. Model-Ready Prompt Template

```text
Implement task OS-NNN from
docs/ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md.

Repository rules:
- Work only in the task's owned files and the smallest required import/export.
- Do not implement later tasks.
- Build toward the target contract; do not add customer compatibility shims.
- Never allow a query without tenant and ACL scope.
- Do not deploy or change production configuration defaults.
- Add focused tests for success, failure, tenant isolation, and idempotency where applicable.

Before editing:
1. Confirm every dependency listed for OS-NNN exists in this branch.
2. Read the owned files and their current tests.
3. If a dependency or required contract is absent, stop and report exactly what is missing.

Before handoff, run:
PYTHONPATH="$PWD/services/api:$PWD" pytest <targeted-test-files> -q
PYTHONPATH="$PWD/services/api:$PWD" pytest services/api/tests -q
git diff --check

Commit the result using:
<type>(search): OS-NNN <short description>

Return:
- commit hash
- changed files
- tests and results
- assumptions
- remaining risks or follow-up task IDs
```

## 11. Review Protocol

Every implementation task requires a separate review model or human reviewer.
The reviewer should inspect, in order:

1. Tenant and ACL fail-closed behavior.
2. Idempotency, replay, deletion, and error recovery.
3. Public contract compatibility and provider leakage.
4. Test quality, including negative and cross-tenant cases.
5. Operational bounds: timeouts, retries, batch sizes, memory, and logging.
6. Scope compliance with the task packet.

A task is not complete merely because tests pass. The owned acceptance evidence
must be visible in the commit.

## 12. Integration Gates

Run from the repository root after every merge wave:

```bash
PYTHONPATH="$PWD/services/api:$PWD" pytest services/api/tests -q
npm --prefix apps/support-web run typecheck
npm --prefix apps/support-web test -- --run
git diff --check
```

When OpenSearch integration tests exist:

```bash
docker compose --profile opensearch up -d opensearch
PYTHONPATH="$PWD/services/api:$PWD" pytest services/api/tests -m opensearch -q
docker compose --profile opensearch stop opensearch
```

Infrastructure changes additionally require:

```bash
helm lint deploy/helm/api
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/azure validate
```

## 13. Human Approval Checkpoints

Lower-capability models may prepare evidence but may not make these decisions:

- Select the Azure OpenSearch operating model or commercial provider.
- Approve index topology exceptions for dedicated tenants.
- Set production relevance, latency, availability, or cost thresholds.
- Approve customer data and behavioral-event retention.
- Enable canary traffic or production cutover.
- Remove Qdrant before the explicit retirement task and local validation gate.

## 14. Initial Definition of Done

The roadmap itself is execution-ready when:

- Every implementation item has one deliverable, dependencies, ownership, and
  acceptance evidence.
- Merge waves prevent known file collisions.
- Delegated prompts contain stop conditions and validation commands.
- Human-only decisions are explicit.
- There is no customer compatibility requirement. Local defaults may change
  after the relevant OpenSearch validation gate is approved.
