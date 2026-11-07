# Canary plan: OpenSearch for chat retrieval over file chunks (RO-7)

**Status: APPROVED by the owner on 2026-11-06 ("approve the RO-7 canary plan"). Nothing here is deployed or enabled.**

**Scope of the approval.** The owner approved this plan as written: the stages, gates, rollback triggers and the stated percent steps. It does **not** authorize any cloud change, turning on any flag in a deployed environment, running a stage, or retiring Qdrant. Each deployed change needs its own request in its own task, and the Qdrant retirement section remains a set of criteria, not a decision. The canary tenant and latency budget were then set on the owner's instruction (section "Defaults set 2026-11-06"); the remaining error thresholds were then set the same way (section "Error thresholds set 2026-11-06"). Nothing in the plan is now undecided; Stage 0 and Stage 1 are blocked only by the preconditions and by building the log query or dashboard.

It follows `docs/RAG_PIPELINE_OPENSEARCH_INDEXER_PLAN.md` (RO-1 to RO-6 are merged) and does not retire Qdrant.

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

## Defaults set 2026-11-06 (owner: "set the canary tenant and latency budget to your recommended defaults")

These are my recommended values, adopted on the owner's instruction. **None is measured**: no OpenSearch chunk latency has been observed anywhere, so treat them as starting points and change them only by recording a new dated entry here.

**Canary tenant: `default`.** It is the only tenant that exists (no customers yet), it is the tenant the ingestion sink writes today, and single-tenant mode already maps to it, so a canary on it affects no customer. Percent buckets cannot name a tenant (`default` sits at canary bucket 75 and shadow bucket 18, so the 10% and 5% steps would never include it), so the first two stages use named cohorts:
- Stage 1 (shadow): `OPENSEARCH_SHADOW_ENABLED=true`, `OPENSEARCH_SHADOW_TENANTS=default`.
- Stage 2 (canary): `OPENSEARCH_CANARY_TENANTS=default`.
- The percent steps in the table apply from the point a second tenant exists; until then the stages run on the named cohort alone.
- **Limit of a one-tenant canary:** it cannot show live cross-tenant isolation. Before Stage 2, re-run `tests/pipelines/test_opensearch_indexer_integration.py` (the two-tenant isolation case) against the deployed index, and keep the zero-leakage rule.

**Latency budget** (OpenSearch chunk query only; the query embedding is shared with Qdrant and excluded):
- p95 at most **300 ms**, p99 at most **800 ms**, and p95 no more than **1.5x Qdrant's p95** in the same shadow window.
- Hard per-request timeout **1.5 s** (`OPENSEARCH_RETRIEVAL_TIMEOUT_SECONDS`, default now 1.5): on timeout Qdrant answers, and the timeout counts as an error toward the 1% error gate.
- Why: chat retrieval runs before an LLM call that takes seconds, so a few hundred milliseconds is a small share; the API-wide search timeout (10 s) is far too loose for chat.
- Measured by the log lines `Retrieval shadow: ... qdrant_ms= opensearch_ms=` and `Retrieval opensearch: ... ms=` (added with these defaults). Nothing aggregates them yet; a dashboard or log query is still to be built.

## Error thresholds set 2026-11-06 (owner: "set the remaining error thresholds to your recommended defaults")

Again my recommended values on the owner's instruction, **unmeasured**, and changeable only by a new dated entry. They add to the stage table's existing gates (errors 1%, golden-set nDCG@10 within 5% of Qdrant, zero cross-tenant results).

| Signal | Threshold | Action |
|---|---|---|
| Error rate (provider error or timeout; each one makes Qdrant answer) | at most 1% over the stage window (existing gate); **above 5% over any rolling 15 minutes** | window gate: do not advance. Burst: set `OPENSEARCH_ROLLBACK=true` the same working day |
| Qdrant-fallback rate | the same events as the error rate, so it is not a separate budget | none beyond the row above |
| Empty results where Qdrant had at least one (from the shadow log counts) | at most 2% of shadowed requests | above 2%: do not advance; investigate before Stage 2 |
| Golden-set recall@10 | not worse than Qdrant by more than 5% (the same rule as nDCG@10) | do not advance |
| Shadow overlap (mean, chunk text) | **alarm only below 0.30**; it is a comparison, not a quality measure, since both systems chunk and rank differently | investigate; never a rollback trigger alone |
| Index/source document count (Stage 0 reconcile) | exactly equal; any failed bulk write fails the job | fix and re-run before Stage 1 |
| Cross-tenant result | zero tolerance (existing) | immediate `OPENSEARCH_ROLLBACK=true` |
| Sample size | decide a stage only after **at least 200 retrievals** and its minimum hold; fewer means extend the hold | with one tenant and low volume, expect longer holds |

**What is and is not automated:** the retrieval path falls back to Qdrant per request, and the OpenSearch provider has its own circuit breaker (opens after 3 consecutive failures). There is **no automatic rollback and no aggregation**: error rate, empty-result rate and overlap come from log lines (`Retrieval shadow`, `Retrieval opensearch`, and the fallback warning) that nobody queries yet. Until a log query or dashboard exists these thresholds cannot be checked, so building it is a precondition for Stage 1.

## Not decided here
Percent steps and week-long holds are proposals. Latency budget, error thresholds beyond the 5% nDCG rule, and the canary tenant choice are the owner's.
