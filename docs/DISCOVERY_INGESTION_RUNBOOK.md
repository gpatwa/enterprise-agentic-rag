# Discovery product ingestion: runbook

Data Operations for the ESCI work (`docs/DISCOVERY_ESCI_SCOPE.md`, packet E1). The pipeline is `services/discovery-api/app/ingest`. It reads local files, validates them, picks a reproducible subset and writes a manifest. **It does not index, call a model, touch a database or use the cloud.** It is tested only on synthetic fixtures; no ESCI file has been downloaded or read.

## Rules
- Dataset files and built subsets live under `services/discovery-api/data/` (git-ignored) or another untracked path. Never commit or push them, and never copy them to cloud storage. ESCI's data terms are not confirmed (`license_status` stays `unconfirmed` in every manifest until the owner records a decision).
- Cite Reddy et al. (2022), arXiv:2206.06588, in any report that uses the data.

## Commands (run from `services/discovery-api`, with `PYTHONPATH=.:../..`)
```bash
python -m app.ingest build --products data/esci/products.csv --examples data/esci/examples.csv --dataset-version <recorded version or date>
python -m app.ingest build --products data/esci/products.csv --examples data/esci/examples.csv --dataset-version <same> --out data/subsets/us-25k-seed7
python -m app.ingest verify --out data/subsets/us-25k-seed7
```
The first command is a dry run: it prints counts and writes nothing. The second writes a new directory and refuses to overwrite an existing one. The third re-reads the subset and fails on count or checksum drift.

## What it does
1. Reads CSV or JSONL (Parquet needs `pyarrow`, which is not a dependency; convert or install it locally).
2. Keeps products judged in the small version for the chosen locale (default `us`).
3. Quarantines bad rows with a fixed reason code and never copies row text into the report: `missing_product_id`, `empty_title`, `title_too_long`, `control_characters`, `locale_mismatch`, `conflicting_duplicate`. Identical duplicates are kept once; conflicting ones are dropped and counted.
4. Selects up to `--limit` products by hashing `seed:product_id`, so the same inputs and seed give the same subset regardless of row order.
5. Writes `products.jsonl`, `quarantine.jsonl` and `manifest.json` (dataset and version, file SHA-256s, locale, limit, seed, counts, subset checksum, time).

## Rebuild
The subset is derived from the source files plus the manifest. To rebuild: same files (check the SHA-256s in the manifest), same locale, limit and seed, then `verify`.

## Not verified
- Column names follow the ESCI files as recalled (`product_locale`, `product_title`, `product_bullet_point`, `small_version`, ...). A missing column fails loudly; confirm against the real files.
- Parquet reading and behavior on the real file sizes (millions of rows) are untested.
- Indexing the subset into OpenSearch (E3) is not built.

## Evaluating a subset (E4)

```bash
python -m app.evaluation.product_search --subset data/subsets/us-25k-seed7 --examples data/esci/examples.csv --out data/reports/bm25-seed7.json
```

- It first runs the same drift check as `verify`, so a report can only describe an intact subset.
- Judgments are restricted to products in the subset, and the dropped counts are in the report (`judgments_outside_subset`, `queries_without_relevant_in_subset`, `conflicting_pairs_dropped`).
- Queries are split by hash into **held-out** and **dev**. The headline is the `held_out` block; the dev block is for tuning only. Defaults: seed 7, 30% held out (`--held-out-fraction`).
- Each query runs `--repeats` times (default 3); `consistent_across_repeats` says whether the rankings were identical.
- Each block gives graded nDCG@k (mean, min and max across repeats), Exact recall@k, the share of the top-k that was judged at all, the label mix of the top-k (E, S, C, I, unjudged) and the worst queries (the regression list).
- `compare_reports(baseline, candidate)` flags a fall in mean nDCG and any worst-list query that got worse. Keep reports; a change is judged against the last one.
- The baseline retriever is an in-memory BM25 over title, brand, color, bullets and description. It is a floor to beat, not a claim about Discovery.

Not verified: gains (Exact 1, Substitute 0.1, Complement 0.01, Irrelevant 0) follow the ESCI task as recalled; the report was only run on synthetic fixtures. Product relevance says nothing about Discovery's experience ranking or engagement.

## Indexing a subset (E3)

```bash
DISCOVERY_OPENSEARCH_URL=http://localhost:9200 python -m app.opensearch.products load --subset data/subsets/us-25k-seed7
```

- It runs `verify` on the subset first, creates the product index (strict mapping, separate from the experience catalog and its aliases) if absent, upserts by `product_id` in batches of 500, refreshes, and prints received, accepted, failed, indexed and expected counts. The exit code is 0 only if nothing failed and the index count equals the manifest's `selected`.
- Re-running is idempotent. The index is derived: rebuild it from a verified subset directory.
- `ProductRetriever(client, index)` is a `(query, k) -> ids` callable, so it drops into `evaluation.product_search.evaluate` next to the BM25 baseline for a like-for-like comparison.
- Lexical only (multi_match over title, brand, color, bullets, description). No embeddings, no model calls.

Verified on 2026-11-04 against a local OpenSearch 2.15.0 container with a 1000-product synthetic subset (1000 in, 1000 indexed, re-run unchanged). Not verified: the real ESCI files, any scale beyond 1000 documents, the pilot VM, and relevance quality (synthetic titles say nothing about it).

## Searching products (API and web)

`POST /api/discovery/v1/products/search` takes `{query, locale?, page?, page_size?}` and returns ranked products
(`product_id`, `title`, `brand`, `color`, `snippet`, `rank`, `score`) plus `total_matches`. The web app shows it as
the "Search products" section. It is BM25 over the index loaded in the previous section.

- A multi-word query must match every word; only if no product does, it widens to any word and the response says `match: "any"` (the web page shows a notice).
- Needs `DISCOVERY_SEARCH_BACKEND=opensearch`; otherwise the response is a typed `not_configured` error.
- A cluster failure returns a typed `search_unavailable` error with no results and no detail. There is no fallback.
- Paging stops at result 1000. `locale` filters on the ESCI locale code (`us`, `es`, `jp`).
- Policy: products carry no age or safety gate and no user profile; the body takes no identity. With
  `DISCOVERY_AUTH_ENABLED=true` a valid bearer token is still required. The owner can overrule the no-gate choice.
- Verified with an in-process fake cluster only. Not run against a live node or real ESCI data.
