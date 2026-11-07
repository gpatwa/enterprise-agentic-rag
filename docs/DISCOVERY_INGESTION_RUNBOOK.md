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
1. Reads CSV, JSONL or Parquet. Parquet needs `pyarrow`, which is not a dependency (see the 2026-11-06 section for how it was verified); it is streamed in batches and only the needed columns are decoded.
2. Keeps products judged in the small version for the chosen locale (default `us`).
3. Quarantines bad rows with a fixed reason code and never copies row text into the report: `missing_product_id`, `empty_title`, `title_too_long`, `control_characters`, `field_too_long`, `locale_mismatch`, `conflicting_duplicate`. Identical duplicates are kept once; conflicting ones are dropped and counted.
4. Selects up to `--limit` products by hashing `seed:product_id`, so the same inputs and seed give the same subset regardless of row order.
5. Writes `products.jsonl`, `quarantine.jsonl` and `manifest.json` (dataset and version, file SHA-256s, locale, limit, seed, counts, subset checksum, time).

## Rebuild
The subset is derived from the source files plus the manifest. To rebuild: same files (check the SHA-256s in the manifest), same locale, limit and seed, then `verify`.

## Not verified
- Column names follow the ESCI files as recalled (`product_locale`, `product_title`, `product_bullet_point`, `small_version`, ...). A missing column fails loudly; confirm against the real files.
- Behavior on the real ESCI files. Parquet and the 25,000-product build were exercised on 2026-11-06 on synthetic data only (see the section at the end).

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
- Verified with an in-process fake cluster only. Not run against a live node or real ESCI data. (A live-node run on synthetic data is recorded in the next section.)

## Scale run on synthetic data, 2026-11-06

**What this is and is not.** About 200,000 fictional ESCI-shaped products and about one million matching example rows, generated by a throwaway script and kept outside the repository. **The labels are synthetic, so the relevance numbers below say nothing about real relevance or about ESCI.** The point was to find defects and see how the pipeline behaves at this size. No ESCI file was read, no license is confirmed, nothing was downloaded, and no cloud or paid API was used (hashing and lexical search only).

**Machine and setup.** Apple M3, 8 cores, 16 GiB; macOS `/usr/bin/time -l` (peak = "maximum resident set size"). Local OpenSearch 2.15.0 (`opensearchproject/opensearch:2.15.0`, single node, security disabled, `-Xms512m -Xmx512m`), API served by `uvicorn` on the same machine (one worker, `DISCOVERY_SEARCH_BACKEND=opensearch`). The load generator, API and OpenSearch share the laptop, so these are not capacity numbers for the pilot VM.

**Input.** `products.csv`: 200,374 rows (113.6 MB; about 0.5% deliberately defective rows: empty titles, control characters, 25,000-character descriptions, identical and conflicting duplicates; 8% non-US rows). `examples.csv`: 1,019,267 rows over 30,000 queries (52 MB; 60% of queries in the small version). Parquet copies (ESCI-like types: int64 ids and flags, nulls for empty strings) were made with pyarrow.

### Commands and measurements
```bash
python -m app.ingest build --products products.csv --examples examples.csv --dataset-version synthetic-20261106 --limit 25000 --out <new dir>
python -m app.ingest verify --out <dir>
DISCOVERY_OPENSEARCH_URL=http://localhost:9210 python -m app.opensearch.products load --subset <dir>
python -m app.evaluation.product_search --subset <dir> --examples examples.csv --out <report.json> [--retriever opensearch]
```

| Step | Result | Wall time | Peak memory |
|---|---|---|---|
| `build` (CSV), first run, before fixes | **crashed**: `MaintenanceError: document collection exceeds the bounded limit` | 5.1 s | n/a |
| `build` (CSV), after the checksum fix only | 25,000 selected of 176,962 candidates | 4.4 s | 452 MiB |
| `build` (CSV), final (two-pass) | same subset, checksum `8f4747e66155` | 5.8 s | **150 MiB** |
| `build` (Parquet, pyarrow 26.0.1) | same counts and same checksum as CSV | 3.2 s | 369 MiB |
| `verify` | `ok selected=25000` | 0.95 s | 56 MiB |
| `load` (list-based, before streaming) | 25,000 received, accepted, indexed; 0 failed | 2.9 s | 159 MiB |
| `load` (streaming, final, fresh index) | 25,000 received, accepted, indexed; 0 failed; count equals manifest | 6.2 s (an idempotent re-run took 2.1 s; timings vary between runs) | **66 MiB** |
| Index size | 6.8 MB on disk for 25,000 documents | | |

Quarantine from the build (200,374 rows read): `empty_title` 142, `control_characters` 193, `field_too_long` 185, `conflicting_duplicate` 164, others 0. Rows for products not judged in the small version are skipped silently, as before.

### Product-search latency through the real route
`POST /api/discovery/v1/products/search`, 200 varied queries (single words; adjective, noun, color and brand combinations; rare tokens; two-word queries with no joint match that widen to any-word; 14-word queries; nonsense that matches nothing; one in four with `locale: us`, one in five on pages 1 to 3, some with `page_size: 25`), 20 warm-up requests not counted, over HTTP on loopback:

| Run | p50 | p95 | p99 | max | errors | throughput |
|---|---|---|---|---|---|---|
| sequential, first | 7.4 ms | 44.2 ms | 88.3 ms | 306.9 ms | 0 | 66 qps |
| sequential, second | 5.9 ms | 17.3 ms | 61.5 ms | 73.8 ms | 0 | 119 qps |
| 8 concurrent clients | 20.6 ms | 66.9 ms | 83.8 ms | 92.7 ms | 0 | 284 qps |

62 of the 200 queries widened to any-word (the `OR` path is the slow tail) and 20 returned no products. 25,000 documents is small; this says nothing about 100,000 documents or about the 4 GiB pilot VM.

### Evaluation (E4) on the subset: BM25 baseline versus the OpenSearch retriever
Held-out queries: 5,274 (dev: 12,306; 383 queries had no Exact or Substitute product in the subset and were dropped; 527,344 judgments pointed at products outside the 25,000). k = 10, 3 repeats; both retrievers were consistent across repeats.

| Retriever | nDCG@10 (held-out) | Exact recall@10 | Judged share of top 10 | Wall time | Peak memory |
|---|---|---|---|---|---|
| In-memory BM25 | 0.0836 | 0.185 | 3.3% | 48.8 s | 337 MiB |
| OpenSearch (`multi_match`, OR) | 0.0839 | 0.184 | 3.3% | 130.7 s | 159 MiB |

**Read this plainly:** the labels are generated from the same fictional vocabulary the titles use, only 14% of judged products are in the subset (so 97% of each top 10 is unjudged and counts as gain 0), and both retrievers are lexical. The two numbers being close shows only that the OpenSearch retriever behaves like a BM25 baseline here. They say nothing about real relevance, ESCI, or Discovery's experience ranking. The harness's OpenSearch retriever uses `OR` semantics, while the API route tries all-words first, so the harness does not measure the route's exact behavior.

### Defects found and fixed
1. **The default build could never run.** `ingest` took its checksum from `app.indexing.maintenance.checksum_ids`, which refuses more than 10,000 ids (a bound for experience-catalog rebuild manifests). Every build above 10,000 products, including the documented default `--limit 25000`, raised `MaintenanceError`; the earlier "verified" runs used 1,000 products. `app.ingest.pipeline.checksum_ids` now computes the same digest without the cap, so existing manifests still verify.
2. **A long field aborted the whole build.** A description over 20,000 characters (the model's limit) escaped as a raw pydantic `ValidationError`. Over-long fields are now quarantined as `field_too_long` (a new reason code; row text is still never copied). A CSV cell over 128 KiB (the `csv` default) is now readable instead of raising `csv.Error`, and a malformed CSV or Parquet file is an `IngestError` instead of a traceback.
3. **Memory followed the candidate text, not the subset.** The build held every judged product as a full record (452 MiB at 177k candidates). It now keeps a 16-byte fingerprint per candidate in the first pass and materializes only the selected products in a second pass (150 MiB, same subset).
4. **The Parquet path had never run.** It called `read_table(...).to_pylist()`, materializing the whole file as Python objects, and compared flag columns as strings, so a `small_version` stored as float64 (what pandas writes when a column has nulls) became `"1.0"` and silently judged nothing. Parquet is now streamed in record batches with column projection, and nulls, NaN, bools and whole floats are normalized the way a CSV cell would read.
5. **Slow paths.** BM25 scanned every document per query (8.5 ms per query at 25,000 products, minutes of the evaluation); it now uses an inverted index (1.9 ms; identical rankings on 100 compared queries, plus a randomized test against the old algorithm). The control-character check no longer loops per character in Python. The OpenSearch `load` now streams the subset instead of reading it all into memory (159 to 66 MiB).
6. **No way to evaluate the OpenSearch retriever from the command line.** Added `--retriever opensearch [--index NAME]` to `python -m app.evaluation.product_search`.

### Parquet: what was and was not run
Run: the build, with the throwaway virtualenv that already had pyarrow 26.0.1 (nothing was installed anywhere), on 200,374 product rows and 1,019,267 example rows, giving the same subset checksum as the CSV build; and `tests/test_ingest_parquet.py` there (8 tests). Those tests skip when pyarrow is not importable, so a normal install skips the module, and CI (which has no pyarrow) does not run them. That interpreter had pydantic and httpx but not fastapi; the full API suite was run with the project interpreter, which has no pyarrow. Not run: a real ESCI Parquet file (its column types are recalled, not checked), larger Parquet files, compression codecs other than the pyarrow default, and Parquet on cloud storage.

### Not verified
Real ESCI data and its column types; any index above 25,000 documents; the pilot VM; the relevance of anything; the Azure OpenAI embedder (not used); latency under a concurrent write load; the cost of the `OR` fallback on a larger index. The local container and every index created for this run were deleted at the end, and the synthetic files stayed outside the repository.
