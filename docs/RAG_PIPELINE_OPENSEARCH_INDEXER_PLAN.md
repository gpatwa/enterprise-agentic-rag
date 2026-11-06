# RAG ingestion pipeline: OpenSearch indexer plan

Status: **Plan.** Written 2026-11-05 from `origin/main` (`8fbbadc`). Nothing here is an approval or a recorded human gate. No code is changed, no cloud resource is touched, and no Ray cluster is started by this document. This covers the Resolution Intelligence / RAG platform (`pipelines/`, `services/api`), not Analytics or Discovery.

## 1. Question and answer so far

Would the Ray ingestion pipeline work with OpenSearch as the vector store? **Not as written.** It needs a writer and a reader; nothing fundamental blocks it. Findings (read from the repository, nothing run):

| Side | Today |
|---|---|
| Writer | `pipelines/ingestion/main.py` ends in `vector_ds.write_datasource(QdrantIndexer())` and `graph_ds.write_datasource(Neo4jIndexer())`. The word "opensearch" appears nowhere under `pipelines/`. |
| Reader | `retrieve_node` (`services/api/app/agents/nodes/retriever.py`) searches through `_vectordb_client`. The vector-DB factory supports Qdrant only; the Azure AI Search and Pinecone branches raise `NotImplementedError`; there is no OpenSearch provider there. |
| OpenSearch path | A separate subsystem, `services/api/app/search/`, indexes support tickets, comments, articles and their chunks from PostgreSQL through an outbox and worker. It is off by default (`OPENSEARCH_ENABLED=False`, shadow and canary percent 0). |
| Tests | No tests exist for `pipelines/ingestion`. |

## 2. Goal and non-goals

**Goal:** file chunks produced by the Ray pipeline can be written to the same OpenSearch index and schema the API already searches, and the chat retriever can read them, behind flags, with Qdrant untouched until a measured comparison says otherwise.

**Non-goals:** removing Qdrant; changing Neo4j or the graph branch; multimodal/image retrieval; PostgreSQL-sourced support search (already built); any deploy or cloud change.

## 3. Constraints from the existing OpenSearch code

- Documents are `SupportSearchDocument` (`app/search/schema.py`): `document_id`, `tenant_id`, `source_type`, `source_id`, `provider`, `title`, `text`, `acl_tokens` (must include `tenant:{tenant_id}`), `content_hash` (SHA-256 hex), `content_version`, `permission_version`, `embedding_model_version`, `schema_version` (`support-search-v1`), optional `vector`.
- The mapping is `dynamic: False` with a `knn_vector` (HNSW, Lucene, cosine). The dimension is fixed per index by `OPENSEARCH_VECTOR_DIMENSIONS` (default 768 in config and Helm).
- Chunks already have a convention: `map_chunk` makes `source_type = "<type>_chunk"`, `source_id = "<id>:chunk:<n>"`, and `acl_tokens = ("tenant:<tenant>",)`, with a deterministic `document_id` and a content-hash `content_version`. Re-indexing is therefore an idempotent upsert.
- The provider contract is `EnterpriseSearchProvider` (async `ensure_index`, `upsert`, `delete`, `search`); tenant scope is enforced on delete and search.
- Rollout exists: `use_opensearch(tenant_id, canary_percent, enabled, rollback)` buckets tenants deterministically.

## 4. Integration options (owner decision D1)

| Option | How the writer builds documents | For | Against |
|---|---|---|---|
| **A. Reuse the API's schema code (recommended for the first packet)** | Pipeline imports `SupportSearchDocument` and the chunk mapper from `services/api` (the job's `working_dir: "./"` already ships the repo; add `PYTHONPATH=services/api`). Writes through `opensearch-py`. | Guaranteed schema parity; smallest change; testable locally | Couples the pipeline to API modules and `app.config` settings; PII redaction setting must be set |
| B. Outbox | Pipeline writes chunk rows to a PostgreSQL search outbox; the existing worker indexes them | Matches the architecture (PostgreSQL canonical, index derived) | Needs a new canonical table for file chunks and migrations; much larger |
| C. API ingest endpoint | Pipeline posts chunks to an internal API route | Single owner of the schema | New authenticated endpoint, throughput limits, retries |

Option A is a stepping stone, not the end state. If the owner prefers B, this plan's tests and reader work still apply.

## 5. Work packets

| ID | Work | Needs | Evidence |
|---|---|---|---|
| RO-0 | **Decisions D1 to D6** (section 7) | **Owner** | Dated entries in the owner's own words |
| RO-1 | **Check the Ray write contract.** Both indexers are plain classes with `write(batch)` passed to `write_datasource`. Confirm against the installed Ray version whether that is accepted, and if not, wrap each sink in a proper Ray Datasink. Applies to Qdrant today as well | RO-0 | A local run with a tiny input showing rows reach a fake sink; the Ray version used is recorded. Installing Ray is a download and needs the owner's yes |
| RO-2 | **`OpenSearchIndexer`** in `pipelines/ingestion/indexing/opensearch.py`: maps each chunk row to a chunk `SupportSearchDocument` (`source_type` `file_chunk`, tenant-only ACL token, deterministic ID, content hash), batches bulk upserts, retries transient errors, raises on permanent failures, and reports counts. Behind `INGEST_VECTOR_SINKS` (default `qdrant`; `qdrant,opensearch` for dual-write) | RO-0 (D1, D2, D3) | Unit tests with a fake client: schema validity, ID stability, idempotent re-run, tenant token present, dimension mismatch rejected before any write, partial bulk failure surfaced |
| RO-3 | **Local integration test** against the cached OpenSearch 2.15.0 container: ingest a small synthetic document set, count equals expectation, re-ingest changes nothing, a second tenant's query returns nothing from the first | RO-2 | Test run output with the node version; indexes created by the test are deleted |
| RO-4 | **Dimension check.** Confirm the actual output dimension of the embedding path in use (the repo does not state BGE-M3's dimension; I believe 1024, unverified) and set `OPENSEARCH_VECTOR_DIMENSIONS` accordingly, or choose the Gemini 768 path | RO-0 (D3) | A recorded probe of the embed endpoint's output length, or the model's documented size |
| RO-5 | **Reader behind a flag:** in `retrieve_node`, when `use_opensearch(...)` is true, query through `SearchService` (hybrid mode, tenant scope) instead of `_vectordb_client`; keep the graph branch and reranker as they are. In shadow mode run both, return Qdrant's results, and log overlap | RO-2 | Tests for flag off (unchanged behavior), flag on, shadow logging, and fallback on provider failure |
| RO-6 | **Comparison on a golden set.** Use the existing search golden corpus (`docs/execution/enterprise-search/OS-005-search-golden-corpus.md`) or owner-written questions; report recall@k and nDCG@10 for Qdrant and OpenSearch lexical, vector and hybrid, on held-out questions, with repeated runs and a regression list | RO-3, RO-5 | A report with commands, versions and numbers; only what was run |
| RO-7 | **Canary plan.** Per-tenant percent through the existing mechanism, with the rollback flag; define the exit criteria for retiring Qdrant (not retiring it) | RO-6; **owner** | A written rollout record; separate cloud authorization for any deployed change |

RO-1 is worth doing even without OpenSearch, since it decides whether the current pipeline writes anything.

## 6. Risks

- **Dual ingestion paths.** Files go through Ray; support records go through PostgreSQL. The same content could be indexed twice with different IDs. Use a distinct `provider`/`source_type` and document it.
- **Permissions.** Tenant-only ACL tokens match the support-chunk convention but ignore per-file permissions. Files shared within a tenant at different levels would all be visible tenant-wide.
- **Embedding drift.** Changing the embedding model or dimension needs a new index generation and re-embedding; the index spec already carries `embedding_model_version`.
- **Version skew.** The cluster and images use Ray 2.9.0, the pipeline requirements pin `ray[data]==2.9.3`, and `Dockerfile.ingestion` pins `ray==2.54.0`. Resolve before trusting any local result.
- **Duplicate work in the pipeline.** Both branches consume the same chunk dataset without materializing it. As I understand Ray Data's lazy execution, parsing and chunking may run twice per job. Not tested.
- **PII.** Redaction is controlled by `PII_REDACTION_ENABLED` in the API's settings; the pipeline must apply the same rule or index unredacted text.
- **Quality claims.** A comparison on the golden corpus says nothing about production quality.

## 7. Decisions for the owner

1. **D1:** integration option A, B or C?
2. **D2:** ACL for file chunks: tenant-only token (matches support chunks), or real per-file permissions?
3. **D3:** embedding path and dimension: BGE-M3 on Ray Serve (set the index to its real size) or Gemini 768?
4. **D4:** dual-write to Qdrant and OpenSearch during the comparison, or switch writers?
5. **D5:** exclude multimodal/image content from the first packet?
6. **D6:** which tenant and which documents form the golden set and the first canary?
7. **D7:** may I install Ray locally for RO-1 (a download; I will state package, version and size first)?
8. Authorization for RO-1 to RO-6 (local code and verification only), with RO-7 and any deployed change as separate approvals.

## 8. Not verified

- Whether Ray accepts the current indexer classes in `write_datasource` (RO-1).
- BGE-M3's output dimension in this deployment.
- Other validators in `SearchDocument` that could reject a `file_chunk` source type (none seen in the fields read).
- Whether anything in the repository currently runs this pipeline end to end.
- The runtime behavior of any referenced deploy file; nothing was started.
