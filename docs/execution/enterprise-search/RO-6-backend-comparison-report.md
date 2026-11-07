# RO-6: Qdrant vs OpenSearch on the search golden corpus

Run on 2026-11-06 with `services/api/scripts/compare_search_backends.py`. Only what was run is reported here.

## Setup
- **Corpus:** `services/api/tests/fixtures/search` (24 fictional documents, 2 tenants, 12 judged queries, ACL groups). Evaluator: `app/search/evaluation.py`, k=10, minimum grade 1.
- **Embeddings:** Azure OpenAI `text-embedding-3-small`, 1536 dimensions, on the `compass-pilot-openai` account (deployment added for this run; 36 short texts embedded once and cached, so the spend is a few cents at most). The same vectors feed every system.
- **Systems:** OpenSearch 2.15.0 (local container) in lexical, vector and hybrid mode through the API's own `OpenSearchProvider`; Qdrant v1.15.0 (local container, cosine) vector search with a tenant payload filter plus the same visibility rule as the API (`_source_is_visible`) applied to its results.
- **Repeats:** 3 runs; results identical every time (`consistent_across_repeats: true`).

## Results (means over 12 queries)

| System | recall@10 | MRR | nDCG@10 | ACL leaks | duplicate IDs |
|---|---|---|---|---|---|
| OpenSearch lexical (BM25) | 0.625 | 0.750 | **0.668** | 0 | 0 |
| OpenSearch vector | 0.625 | 0.750 | 0.639 | 0 | 0 |
| OpenSearch hybrid | 0.625 | 0.750 | 0.650 | 0 | 0 |
| Qdrant vector | 0.625 | 0.750 | 0.639 | 0 | 0 |

## What this does and does not show
- **OpenSearch vector and Qdrant vector agree exactly** (nDCG 0.6387, same top results on every query). On pure vector search the engines are interchangeable on this data.
- **Release thresholds from OS-057 are met on this corpus:** ACL leakage 0, duplicate IDs 0, no nDCG regression versus the Qdrant baseline (OpenSearch hybrid 0.650 vs Qdrant 0.639).
- **It cannot rank the systems.** Recall and MRR tie because three of the 12 queries have no relevant document by design (ACL-hidden, cross-tenant, no-match), which caps recall and MRR at 0.75 for everyone, and with 24 documents k=10 returns nearly every in-tenant document. The nDCG gaps (0.639 to 0.668) are well inside what 12 queries can resolve. No held-out split was used: nothing was tuned, so all 12 are evaluation queries, and there is no confidence interval.
- **Not covered:** file-chunk retrieval (this corpus is support records, not chunks), real corpus size and latency, BGE-M3 (1024) embeddings, the shadow overlap on real traffic, and Qdrant's own lexical or fusion behaviour (the legacy "Python lexical plus Qdrant" fusion baseline was not run).

Reproduce: start OpenSearch (`docker compose --profile search up -d opensearch`) and Qdrant, then run the script with the three `AZURE_OPENAI_*` variables set (see its docstring). Embeddings are cached with `--cache`.
