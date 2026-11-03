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
