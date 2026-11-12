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
- **Version skew (resolved 2026-11-11).** Ray 2.60.0 (latest on PyPI, published 2026-11-04) everywhere: `deploy/ray/*` (`rayVersion` and `rayproject/ray:2.60.0-py310[-gpu]` images; both tags exist on Docker Hub), `pipelines/ingestion/requirements.txt`, `requirements-ingestion.txt` and `Dockerfile.ingestion`. **Run:** in a clean Python 3.12 virtualenv with `ray[data]==2.60.0`, `numpy 1.26.4` (the repo pins `numpy<2.0.0`), `pyarrow 22.0.0`, `pandas 3.0.6`, `qdrant-client 1.7.3`, `pydantic 2.6.0` and `services/api/requirements.txt`, against local Qdrant 1.7.3 and OpenSearch 2.15.0 containers: `tests/pipelines` and `tests/test_tenant_data_isolation.py` with `OPENSEARCH_INTEGRATION=1 RAY_SINK_INTEGRATION=1`: **108 passed, 0 skipped**, including the 4 real-Ray sink tests. **Found:** with the previous unbounded `pyarrow>=14.0.0` and `numpy<2.0.0`, pip resolves pyarrow 26.0.1, which cannot be imported (needs NumPy 2); `requirements-ingestion.txt` now bounds pyarrow below 23 (22.0.0 verified; 23-25 untested). Plain `ray` has no pandas, which Ray Data imports; the image gets it from `unstructured`. **Also run (2026-11-12).** The image built from `Dockerfile.ingestion` (linux/arm64 native; Python 3.11.18, Ray 2.60.0, numpy 1.26.4, pyarrow 22.0.0): all ingestion modules import, a valid PDF is parsed to text and chunked, `read_binary_files(include_paths=True)` returns `bytes` and `path`. This found two image defects (fixed in #152): `onnxruntime` 1.15.1 (required by `unstructured-inference`) cannot load on Debian 13's glibc, so the base is pinned to bookworm, and `matplotlib` had been trimmed but is imported at load. On a local `kind` cluster with the KubeRay operator **1.7.2** (the bootstrap scripts now install it): `rayproject/ray:2.60.0-py310` head and CPU worker reach `ready`, a task runs on the worker and a Ray Data job returns the right sum; the three `deploy/ray` manifests pass `kubectl apply --dry-run=server --validate=strict` against the operator's CRDs; a `RayService` built from `ray-serve-embed.yaml` (stand-in app, CPU) reaches `Running`, serves `POST /embed`, and scales from zero. This found two manifest defects (fixed here): `target_num_ongoing_requests_per_replica` is not a Ray 2.60 field and was silently ignored (Serve used its default target of 2; now `target_ongoing_requests`), and the head ports were unnamed so the operator failed with `dashboard port is not found` and the RayService never left Initializing.
- **Found, not changed:** the `runtime_env.pip` list in `pipelines/jobs/ray_job.yaml` resolves on `rayproject/ray:2.60.0-py310` (`pip install --dry-run`, no resolver error) but installs with conflicts (`pip check`): `langchain==0.1.0` pulls `packaging` 23.2 while Ray 2.60.0 requires `>=24.2` (Ray still imports and runs tasks and Ray Data), and `pydantic==2.6.0` is below what the image's `fastapi` needs, so `import ray.serve` fails in that environment. The ingestion job does not import Serve (it calls the Serve endpoints over HTTP), and its sink modules import under these pins. Checked with a subset install (`langchain`, `pydantic`, the clients); the `torch`/`unstructured`/`sentence-transformers` installs were not run (multi-GB CUDA wheels). **Changed (2026-11-12):** `langchain==0.1.0` (and the unpinned `langchain` in `s3_event_handler.py`) is replaced by `langchain-text-splitters>=0.3,<1`. Only that package is imported (`chunking/splitter.py`), and `langchain==0.1.0` predates it, so the old list could not import the chunker at all (checked in a clean venv: `ModuleNotFoundError: langchain_text_splitters`). On `rayproject/ray:2.60.0-py310` the new pins install with `packaging` 24.2 (Ray's own conflict is gone), the splitter imports and chunks, and `ray` imports. Still reported by `pip check` there, unchanged by this edit: `pydantic==2.6.0` below `fastapi`'s floor (so `import ray.serve` still fails in that environment), `protobuf` 7 pulled in by `qdrant-client` against `grpcio-reflection`/`opentelemetry-proto`, and image tooling (`virtualenv`, `conda-lockfiles`). Not run: the full list with `unstructured[pdf,docx]` and `sentence-transformers`, or a real job submission.
- **Still not verified:** the real Serve apps (`embedding_engine`, `vllm_engine`): they need a GPU and model downloads this machine does not have, and the `vllm==0.3.0` / `torch==2.1.2` runtime_env against Ray 2.60 is unchecked; GPU scheduling and Karpenter scale-up on EKS/AKS; the `linux/amd64` image running Ray (it builds and imports; starting Ray under emulation timed out in the dashboard agent); any real S3 read.
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

### Owner sign-off: Ray 2.60 alignment (2026-11-12)

The owner (Gopal Patwa) reviewed PRs #150 to #157 in chat on 2026-11-12 and approved three decisions:

1. **Serve autoscaling targets.** `target_ongoing_requests: 50` (embed) and `20` (LLM) are approved as the values in `deploy/ray/ray-serve-embed.yaml` and `ray-serve-llm.yaml`. They are the values the manifests always stated; they took effect for the first time in #153 and have not been load-tested.
2. **KubeRay operator 1.7.2.** The upgrade from 1.0.0 is approved for the existing clusters; it applies the next time `scripts/bootstrap_cluster.sh` or `scripts/bootstrap_cluster_azure.sh` runs against them (#151).
3. **Merge on green.** The standing instruction to merge own pull requests once every check is green covers #155 (`ray_job.yaml` and `s3_event_handler.py` pip lists, plus the first CI runner pin) and #156 (deploy workflows pinned to `ubuntu-24.04`).

What this sign-off does not cover: it does not authorize running the bootstrap scripts, deploying, or changing any cloud resource; those still need an explicit request in the task at hand. It does not make any of the items in "Still not verified" (section 6) verified.

## 8. Not verified

- Whether Ray accepts the current indexer classes in `write_datasource` (RO-1).
- BGE-M3's output dimension in this deployment.
- Other validators in `SearchDocument` that could reject a `file_chunk` source type (none seen in the fields read).
- Whether anything in the repository currently runs this pipeline end to end.
- The runtime behavior of any referenced deploy file; nothing was started.

## 9. Decision record and RO-1 result (2026-11-06)

**Owner choice (2026-11-06, in chat):** "Use my recommended defaults" for D1 to D7, building RO-1 onward as separate PRs and stopping only at a security or spend gate. The defaults I am working to: D1 option A; D2 tenant-only ACL token; D3 BGE-M3 with the real dimension confirmed in RO-4 (not assumed); D4 dual-write while comparing; D5 no multimodal content in the first packet; D6 a synthetic golden set built for this purpose, with real tenant data only on the owner's say; D7 installing Ray locally approved (done: `ray[data]==2.54.0` in a throwaway virtualenv outside the repo, about 500 MB, the version in `Dockerfile.ingestion`). RO-7 and any deployed change still need their own approval.

**RO-1 finding (run on Ray 2.54.0, Python 3.12):**
- `main.py` called `vector_ds.write_datasource(QdrantIndexer())`. On 2.54.0 a dataset has **no** `write_datasource` (`AttributeError`), so the pipeline as pinned in `Dockerfile.ingestion` could not have written to Qdrant or Neo4j.
- `write_datasink` expects a `Datasink` whose `write(blocks, ctx)` receives Arrow blocks, not `list[dict]`. `pipelines/ingestion/indexing/ray_sink.py` wraps any plain `write(batch)` indexer so it receives `list[dict]`, and falls back to the old call when `write_datasink` is absent.
- Tests: 2 without Ray, 3 with a real local Ray (every row of a 25-row dataset reaches the sink as a dict; sink errors fail the write; empty blocks are skipped). All 5 pass with Ray 2.54.0.
- **Not verified:** Ray 2.9.0/2.9.3 (the cluster and `requirements.txt` versions; no Python 3.11 here), so the fallback is untested; the real `QdrantIndexer`/`Neo4jIndexer` against live services; whether the sink objects pickle cleanly into workers (the test's `FileSink` did; the Qdrant and Neo4j clients were not tried). The version skew (cluster 2.9.0, requirements 2.9.3, image 2.54.0) is the first thing to settle before any deploy.

### RO-2 result (2026-11-06)

`pipelines/ingestion/indexing/opensearch.py` (`OpenSearchIndexer`) and `sinks.py` (`INGEST_VECTOR_SINKS`, default `qdrant`; `qdrant,opensearch` dual-writes; unknown or empty values fail at start). Documents come from a new public `map_file_chunk` in `services/api/app/search/support_mapper.py`, so schema, ACL (`tenant:<tenant>` only), PII redaction and ID format match the support path.

- **ID and idempotence:** `source_id = <filename>:chunk:p<page>:<sha256(text)[:16]>`. Re-running the same file gives the same IDs, so a re-run upserts in place. Editing a file changes the IDs of changed chunks and **leaves the old chunks indexed**; there is no delete-by-file yet.
- **Safety:** wrong vector length rejects the whole batch before any provider is created; image rows are skipped and counted; a chunk with no `filename` fails the job; permanent bulk failures fail the job with document IDs and codes only (no text); retryable item failures are retried for just those documents, twice, then fail.
- **Needs from the environment:** `services/api` on `PYTHONPATH`, the API's `OPENSEARCH_*` settings, and `INGEST_OPENSEARCH_INDEX` naming the index generation (required; the indexer creates it with the API mapping if absent and refuses a drifted one). Activating an alias is still a separate operator step.
- **Dual-write** materializes the vector dataset once so each sink does not recompute embeddings. That path is not exercised at any scale.
- **Tenant:** `main.py` builds the indexer with the default tenant `default`, exactly as the Qdrant sink does today. Real per-tenant ingestion is not in this packet.
- Tests: 15 new, with a fake provider only (full API suite 639 passed). **Not verified:** a real OpenSearch node (RO-3), the real Ray run with this sink, and that the pipeline image has `opensearch-py` and the API modules (`pipelines/ingestion/requirements.txt` does not list `opensearch-py`).

### RO-3 result (2026-11-06)

Run against a local OpenSearch **2.15.0** container (`docker compose --profile search up -d opensearch`), opt-in with `OPENSEARCH_INTEGRATION=1` (`services/api/tests/pipelines/test_opensearch_indexer_integration.py`, 3 tests, all pass; each test's index is deleted, none left over):
- 30 chunks written; a re-run leaves the count at 30; stored documents carry `source_type=file_chunk`, `acl_tokens=["tenant:acme"]`, an 8-value embedding, the model version and a 64-character content hash.
- A second tenant's chunks do not appear in the first tenant's search and the reverse (searched through the API's `OpenSearchProvider`, lexical mode).
- A vector-dimension mismatch against an existing index writes nothing and fails with `field definition changed: embedding`.

**Bug found and fixed:** the API's `classify_mapping_compatibility` treated a real node's `dynamic: "false"` (string) as different from the proposed `dynamic: False`, so `ensure_index` on any existing index raised "breaking drift". A second write, and any API-side re-run of `ensure_index`, would have failed on a real cluster. Normalized in `compatibility.py` with a unit test. Unit tests with fakes had never caught it.

Still not verified: vector or hybrid search over pipeline-written chunks, scale beyond 30 documents, and the real Ray job end to end.
### RO-4 result (2026-11-06)

**Dimensions by embedding path:**
- **BGE-M3 on Ray Serve** (`services/api/app/models/embedding_engine.py`, used by `BatchEmbedder` for text): **1024**. Source: the model's published `config.json` (`hidden_size` 1024) and its sentence-transformers pooling config (`word_embedding_dimension` 1024), read from Hugging Face on 2026-11-06. The repo comment in `openai_embed.py` saying 4096 was wrong and is corrected. **Not probed:** the deployed `ray-serve-embed` endpoint (nothing is deployed) and the model weights themselves.
- **Gemini multimodal path** (`MultimodalBatchEmbedder`): `GEMINI_EMBED_DIMENSIONS`, default **768**.
- **OpenAI** `text-embedding-3-small` 1536 / `-large` 3072 (documented sizes).

**Consequence:** the API default `OPENSEARCH_VECTOR_DIMENSIONS=768` and Helm `enterpriseSearch.vectorDimensions: 768` do not match the BGE-M3 text path. With the defaults the new indexer rejects every text batch (the dimension guard doing its job). Set `INGEST_VECTOR_DIMENSIONS=1024` for BGE-M3 (new; precedence: argument, this variable, then the API setting). One index holds one dimension, so BGE-M3 text and Gemini multimodal vectors cannot share an index.

**Not changed:** the Helm default and any deployed value. Whether the API's own support-search path embeds with BGE-M3 at 1024 against a 768 index is **not verified**; check it before enabling OpenSearch for chunk retrieval.

### RO-5 result (2026-11-06)

`retrieve_node` (`services/api/app/agents/nodes/retriever.py`) now chooses a vector backend per tenant, with graph search, merging and the reranker unchanged:
- **qdrant (default):** unchanged behaviour. Also the result when no search service was injected, `OPENSEARCH_ENABLED` is false, the canary is 0, or the new `OPENSEARCH_ROLLBACK=true` is set.
- **opensearch:** tenant is inside `OPENSEARCH_CANARY_PERCENT` (the existing `use_opensearch` bucket). Hybrid query through `SearchService`, scoped to the tenant, filtered to `source_type = file_chunk`, using the query embedding already computed. Results from any other tenant are dropped. Any provider error falls back to the Qdrant path for that request.
- **shadow:** tenant is inside `OPENSEARCH_SHADOW_PERCENT` (separate bucket salt) with `OPENSEARCH_SHADOW_ENABLED`. Qdrant's answer is returned; OpenSearch runs alongside and only an overlap line is logged (counts and ratio, no document text). A shadow failure cannot change the reply.
- `main.py` injects the enterprise search service into the retriever when OpenSearch is enabled. Single-tenant mode queries tenant `default`, matching what the ingestion sink writes.
- Tests: 10 new, fakes only (full API suite 652 passed). **Not verified:** a real node through this path, the shadow overlap on real data (RO-6), and latency. Overlap compares chunk text, since the two systems use different IDs; chunks split differently would count as different.

### RO-7 record (2026-11-06)

`docs/RAG_OPENSEARCH_CANARY_PLAN.md` was approved by the owner as written ("approve the RO-7 canary plan"). The approval covers the plan only; every deployed change, flag change in a deployed environment and Qdrant retirement still needs its own request. The latency budget, extra error thresholds and canary tenant remain open and block Stage 1.

**Update 2026-11-06:** on the owner's instruction ("set the canary tenant and latency budget to your recommended defaults") the canary tenant is `default` (named cohorts via `OPENSEARCH_CANARY_TENANTS` / `OPENSEARCH_SHADOW_TENANTS`) and the latency budget is p95 300 ms / p99 800 ms / 1.5 s timeout; see the canary plan. Unmeasured defaults.

**Update 2026-11-06 (later):** the remaining error thresholds were set to recommended defaults on the owner's instruction (empty-result rate, recall@10, a 15-minute burst rule, overlap alarm, minimum sample size); see the canary plan. Nothing in the canary plan is now undecided. They cannot be checked until request logs are aggregated, which is a Stage 1 precondition.

**Update 2026-11-06 (observability):** Prometheus metrics, alert rules (promtool-tested) and a Grafana dashboard for the canary thresholds were built and checked against a real Prometheus fed by the real retrieval code; see the canary plan. Not deployed, Grafana rendering unseen, no alert receiver configured.

## 10. Hardening follow-up (2026-11-06)

Four items after RO-1 to RO-7. Nothing here enables a flag in a deployed environment or changes the canary plan.

### 10.1 Real sinks on a real Ray (pickling check)

Run on Ray 2.54.0 (Python 3.12), Qdrant 1.7.3 and OpenSearch 2.15.0 in local containers, with `opensearch-py` 2.8.0 and `qdrant-client` 1.7.3, 24 synthetic rows in four blocks (so four write tasks ran at once). Opt-in tests: `services/api/tests/pipelines/test_ray_real_sinks_integration.py` (`RAY_SINK_INTEGRATION=1`; the file header has the commands). Defects found by running the real classes, and fixed:

| Defect | Effect | Fix |
|---|---|---|
| `QdrantIndexer` built its `QdrantClient` in `__init__`; the client holds a thread lock | `write_rows(ds, QdrantIndexer())` failed before writing anything ("cannot pickle `_thread.RLock`") | Client created on first use, dropped from pickled state. Same pattern in `Neo4jIndexer` (tested with a stand-in module; the real `neo4j` driver was not installed here) |
| Qdrant point IDs were `uuid4` | Every re-run added a second copy of every chunk | `uuid5` of tenant, file name, page, content type and content hash. The same chunk upserts in place; another tenant's identical file is a different point |
| Parallel write tasks all called `ensure_index` on a fresh index | Losers failed with `resource_already_exists_exception` | `OpenSearchProvider.ensure_index` now validates the winner's mapping instead (an incompatible winner still raises) |
| `OpenSearchError` used keyword-only construction | Any provider error raised in a worker reached the driver as "Failed to deserialize exception" | `__reduce__` added (the `cause` is not carried across processes) |

Results: both sinks wrote exactly 24 rows; a second identical run left 24; a second tenant's identical file added 24 under its own tenant tag (counts 24/24/48); OpenSearch documents carried `source_type=file_chunk`, `acl_tokens=["tenant:<t>"]` and the vector; a wrong-length vector in one block failed the job with a readable message and wrote nothing.

### 10.2 What the pipeline image ships

`Dockerfile.ingestion` installs the **root** `requirements-ingestion.txt` (not `pipelines/ingestion/requirements.txt`, which nothing reads except as documentation) and copies the repository under `.dockerignore`, which excluded `services/api`. So the OpenSearch sink could not import in the image. A real run also showed that plain `opensearch-py` is not enough: without `aiohttp` (the `[async]` extra) the provider fails at its first write with "opensearch-py is required to construct the OpenSearch provider".

Changed: `opensearch-py[async]>=2.4,<3.0`, `pydantic==2.6.0`, `pydantic-settings==2.1.0` (the API's pins) in both requirements files, `pipelines/jobs/ray_job.yaml` and the S3 job handler's `runtime_env.pip`; `.dockerignore` ships `services/api/app` only; `PYTHONPATH=/app:/app/services/api` in the Dockerfile and compose; and the sink adds `services/api` to `sys.path` itself when a Ray `working_dir` ships the repository without a `PYTHONPATH`.

Checked without building the image: `tests/pipelines/test_image_dependencies.py` (pins agree with the API; the sink modules import in a subprocess that blocks every module the declared requirements do not provide, and the same check fails when the new lines are removed), and a trivial `FROM scratch` build with the repository as context showed only `services/api/app` is copied. **Not verified:** that pip resolves the whole file together (ray 2.54.0, unstructured 0.12.0, pydantic 2.6.0), that the image builds, and the Ray 2.9.x cluster. Also noticed and left alone: `httpx`, `google-genai`, `python-docx` and `sqlalchemy` are imported under `pipelines/` but not declared in `requirements-ingestion.txt` (httpx arrives with qdrant-client; the others may be missing), and `ray_job.yaml` pins older `qdrant-client`/`neo4j` than the image.

**Fixed: the pipeline can now read its input.** `process_batch` read `batch["filename"]`, but `ray.data.read_binary_files(..., include_paths=True)` yields `bytes` and `path` (checked on Ray 2.54.0), so the first block raised `KeyError`. A file's identity is now its full path (`pipelines/ingestion/identity.py`, stored as `metadata["source_path"]`, scheme stripped); the base name stays in `metadata["filename"]` for display and for the parsers. Chunk IDs, the OpenSearch `file_id` and so the sweep group by the path, so same-named files in different folders cannot overwrite or sweep each other. Qdrant point IDs now hash the path too, which changes IDs for data written by the earlier, never-runnable path (no such data exists). Verified with unit tests and one `process_batch` call on a Ray-shaped batch with the parser stubbed; not yet run on a live Ray cluster against S3.

### 10.3 Stale chunks on re-ingest (opt-in sweep)

**Problem.** A chunk's document ID includes a hash of its text. Editing a file gives changed chunks new IDs; the old ones stayed indexed.

**Design.** `INGEST_OPENSEARCH_SWEEP=true` (off by default; anything but a recognised true/false value fails at start; setting it without `opensearch` in `INGEST_VECTOR_SINKS` fails at start).
1. At construction on the driver the indexer fixes a run id (`INGEST_RUN_ID`, else a random one; must be unique per run) and the run start time. Every chunk of the run is written with tag `ingest-run:<id>` and `updated_at = run start`. The index mapping is unchanged (`dynamic: false` makes `tags` and `updated_at` the only usable fields). Nothing is stamped when the flag is off.
2. `main.py` calls `finalize_sinks` only after every sink wrote. A failed job never sweeps.
3. The sweep (`OpenSearchProvider.find_stale_file_chunks`, read-only) lists the files the run actually wrote (a composite aggregation over the stamped chunks, so only what landed counts), then the chunks of those files that carry **another** stamp or none **and** are older than the run start. Every query is pinned to the indexer's tenant, provider `ray-ingest` and `file_chunk`.
4. The ids go to the provider's existing `delete(..., scope=<tenant>)`, which re-reads each document and refuses any that is not that tenant's.

**Fail closed.** One concrete index name only (no wildcard, list or system index). Blank tenant, provider or run id refuses. More stale chunks than `INGEST_OPENSEARCH_SWEEP_MAX_DELETE` (default 10000) refuses and deletes nothing. Each returned hit is re-checked against tenant, provider, source type and run stamp, and one foreign hit aborts the whole sweep. A run that wrote nothing, or a missing index, deletes nothing. Any error fails the job after the new chunks are written; the old ones are simply still there for the next run.

**Limits.**
- A file is identified by its `filename` metadata (stored as the title). Two different files with the same name in one tenant are one file to the sweep; ingesting only one of them deletes the other's chunks. Use the full object key as the name before enabling this.
- A file whose new version has no chunks, and a deleted file, are not swept (the run never writes that file). File deletion is a separate feature.
- Names longer than 512 characters have no keyword form and are never swept (safe direction).
- Qdrant is not swept; with dual write its stale points remain.
- The time guard protects a chunk written after this run began (a second job for the same file). Two jobs for one tenant and file at the same time are still not supported.
- Stamping adds `updated_at` to file chunks, which the API's recency scoring may read; compare ranking before enabling on a tenant that is on the canary.
- Documents written before this feature have no stamp or `updated_at` and count as older, so the first sweep of a file also removes its pre-existing stale chunks.

**Evidence.** Unit tests with a fake provider and a recording fake client, plus 7 tests on a real OpenSearch 2.15.0 node and one real Ray run: editing a file with 10 chunks into 6 (4 unchanged) deletes exactly the 6 old chunks while leaving another file of the same tenant, the same file name under another tenant, and another provider's chunk untouched; the delete cap refuses and deletes nothing; a chunk written by a later-starting run survives; dropping the tenant filter from the query makes the test fail (checked by mutation). Dropping the "not this run's stamp" clause alone does not fail them, because the time guard also excludes the run's own chunks; the two are independent guards.

### 10.4 Open question from RO-4: query embedding vs the 768 index

Read from code only; nothing was run or changed. The API's support search (`SupportIndexer._search_enterprise` in `app/support/indexer.py`) embeds the query with the global `embed_client`, which `EMBED_PROVIDER` selects, and always asks for a hybrid search. `OpenSearchProvider._search_vector` rejects a query vector whose length differs from `OPENSEARCH_VECTOR_DIMENSIONS` (config default and Helm `enterpriseSearch.vectorDimensions`: 768) with a `ValueError`, which `_search_enterprise` turns into "enterprise search is unavailable"; there is no lexical fallback in that method. What each configuration in the repository produces:

| Configuration | Query vector | Against 768 |
|---|---|---|
| Default (`EMBED_PROVIDER=ray`, `EMBED_MODEL=nomic-embed-text`, Ollama-style endpoint) | 768 | matches |
| `values-azure.yaml` (`EMBED_PROVIDER=openai`, default `text-embedding-3-small`, no `dimensions` argument) | 1536 | **fails** |
| `values-prod.yaml` (`EMBED_MODEL=bge-m3`, provider `ray`) | 1024 if the endpoint is BGE-M3 | **fails** |
| `EMBED_PROVIDER=gemini` (`GEMINI_EMBED_DIMENSIONS`) | 768 by default | matches |

So the answer is: not "BGE-M3 against 768" by default, but every deployed values file in the repository that sets an embedder produces a vector that does not match the 768 default, and with enterprise search enabled that makes support search fail rather than degrade. Two more observations: (1) `RayEmbedClient` sends `{"model", "prompt"}` and reads `"embedding"` (Ollama's shape), while the repository's own Ray Serve BGE-M3 deployment (`app/models/embedding_engine.py`) takes `{"text"}` and returns `{"embeddings"}`; the two do not speak to each other as written, and which endpoint a deployment really uses is not in the repository. (2) Nothing in the API populates `SupportSearchDocument.vector` for tickets, comments or articles (the mapper, outbox worker, backfill and reindex never embed), so support documents are indexed without embeddings and the vector half of a hybrid query finds only file chunks written by this pipeline. Three numbers must agree before enabling vectors anywhere: the index mapping dimension, `OPENSEARCH_VECTOR_DIMENSIONS` in the API, and the length of the query embedder's output; `INGEST_VECTOR_DIMENSIONS` only sets the first for the pipeline. **Not verified:** the deployed endpoint, the actual output length of any embedder, and behaviour at runtime.

### 10.5 Not verified in this follow-up

Ray 2.9.x; the real Neo4j driver; a Ray cluster (only local Ray); pip resolution and a real image build; Qdrant or OpenSearch beyond the single local nodes; scale beyond a few dozen documents; concurrent sweeps; vector or hybrid search over swept data.
