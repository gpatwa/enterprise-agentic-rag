# Canary plan: OpenSearch for chat retrieval over file chunks (RO-7)

**Status: DRAFT for the owner's approval. Nothing here is deployed or enabled.** It follows `docs/RAG_PIPELINE_OPENSEARCH_INDEXER_PLAN.md` (RO-1 to RO-6 are merged) and does not retire Qdrant.

## What exists now
- **Writer (RO-2):** `INGEST_VECTOR_SINKS=qdrant,opensearch` dual-writes chunks (needs `INGEST_OPENSEARCH_INDEX`, `INGEST_VECTOR_DIMENSIONS`, `services/api` on `PYTHONPATH`).
- **Reader (RO-5):** per-tenant backend choice in `retrieve_node`: Qdrant by default; `OPENSEARCH_SHADOW_ENABLED` plus `OPENSEARCH_SHADOW_PERCENT` compares without changing replies; `OPENSEARCH_CANARY_PERCENT` serves OpenSearch to the bucketed tenants with Qdrant fallback on error; `OPENSEARCH_ROLLBACK=true` forces Qdrant instantly.
- **Evidence so far:** a real-node indexer test (RO-3) and a golden-corpus comparison (RO-6) in which OpenSearch vector matched Qdrant exactly. That corpus is support records, 24 documents, so it says nothing yet about file chunks, scale or latency.

## Preconditions before any stage (each needs the owner)
1. A chunk index exists with the right dimension. BGE-M3 is 1024; the API and Helm default is 768 (RO-4). Pick one and set both sides, since one index holds one dimension.
2. Backfill: existing Qdrant chunks are not in OpenSearch. Re-run ingestion with the dual-write sink over the same source files. Edited files leave stale chunks (no delete-by-file yet), so decide whether to rebuild into a fresh index generation.
3. A golden set of file-chunk questions for the canary tenant (D6). The RO-6 corpus does not cover chunks.
4. Deployed OpenSearch reachable from the API and the ingestion job, with credentials in a secret store. The pilot VM is search-only for Discovery; production OpenSearch for this is not provisioned.
5. Separate cloud authorization for every deployed change.

## Stages
| Stage | Setting | Who sees OpenSearch | Hold until | Roll back if |
|---|---|---|---|---|
| 0. Dual-write | sinks `qdrant,opensearch`, reader unchanged | nobody | document counts match the source (reconcile), no failed bulk writes | any failed write, count drift |
| 1. Shadow | `OPENSEARCH_SHADOW_ENABLED=true`, percent 10 then 50 | nobody (Qdrant answers) | at least a week of logged overlap, no shadow errors above 1%, p95 shadow latency within the agreed budget | errors above 1%, latency over budget |
| 2. Canary | `OPENSEARCH_CANARY_PERCENT` 5, then 25 | those tenants | golden-set nDCG@10 not worse than Qdrant by more than 5% (the OS-057 threshold) and zero cross-tenant results, held for a week each | any cross-tenant result, nDCG regression over 5%, error rate above 1%, `OPENSEARCH_ROLLBACK=true` |
| 3. Majority | 50, then 100 | most tenants | same gates, plus the owner's go | same |

Cross-tenant leakage has no tolerance: one occurrence stops the rollout and triggers `OPENSEARCH_ROLLBACK=true`.

## Exit criteria for retiring Qdrant from chunk retrieval (not part of this plan's approval)
At 100% for at least 30 days with the gates above held, the multimodal image path (Qdrant plus Gemini, 768) has a defined OpenSearch equivalent or stays on Qdrant, a restore-from-source rebuild has been rehearsed, and the owner records a go/no-go. Until then Qdrant keeps receiving writes.

## Metrics to collect (none are wired to a dashboard yet)
Shadow overlap ratio (logged by `retrieve_node`), per-backend error counts and latency, fallback count, golden-set nDCG@10 and recall@10 per stage, document-count reconcile result.

## Not decided here
Percent steps and week-long holds are proposals. Latency budget, error thresholds beyond the 5% nDCG rule, and the canary tenant choice are the owner's.
