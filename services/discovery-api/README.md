# Discovery API

FastAPI service for the immersive discovery vertical. By default it serves a fictional, seeded catalog from memory with no external dependency. See `docs/DISCOVERY_PHASE2_SCOPE.md` and `docs/DISCOVERY_PHASE2_COST_MODEL.md` for the plan and costs.

## Search backends

| `DISCOVERY_SEARCH_BACKEND` | Behavior |
|---|---|
| `memory` (default) | Lexical (and optionally vector) retrieval over the in-memory catalog. |
| `opensearch` | Ranks through OpenSearch. If the cluster is unreachable, serves the in-memory catalog and sets `fallback: true` on the response, so an on-demand cluster can be stopped without breaking the demo. |

Retrieval features are flags: `DISCOVERY_FEATURE_LEXICAL` (default on), `DISCOVERY_FEATURE_VECTOR`, `DISCOVERY_FEATURE_HYBRID` (both default off).

Vectors come from a local hashing embedder (`app/embedding`): deterministic, no model call, no cost. It measures word overlap, not meaning, so it proves the retrieval path rather than semantic quality. A vector match below cosine 0.25 is dropped as noise.

OpenSearch settings: `DISCOVERY_OPENSEARCH_URL`, `DISCOVERY_OPENSEARCH_USERNAME`, `DISCOVERY_OPENSEARCH_PASSWORD`, `DISCOVERY_OPENSEARCH_VERIFY_TLS`. `staging` and `production` require an `https` URL and credentials. The password is never dumped or logged.

OpenSearch applies hard filters (tenant, not blocked, approved, available) and every returned document is re-checked by the same Python eligibility rules the in-memory path uses.

## Run it against a local OpenSearch

```bash
docker compose --profile search up -d opensearch
cd services/discovery-api
export DISCOVERY_OPENSEARCH_URL=http://localhost:9200
PYTHONPATH=.:../.. python -m app.opensearch.bootstrap     # creates the index, loads the demo catalog
DISCOVERY_SEARCH_BACKEND=opensearch DISCOVERY_FEATURE_HYBRID=true DISCOVERY_FEATURE_VECTOR=true \
  PYTHONPATH=.:../.. uvicorn app.main:app --port 8110
```

The bootstrap is safe to re-run (upserts by stable ID). The index is derived data: it can be deleted and rebuilt from the catalog at any time.

## Tests

```bash
cd services/discovery-api && PYTHONPATH=.:../.. pytest -q
DISCOVERY_TEST_OPENSEARCH_URL=http://localhost:9200 PYTHONPATH=.:../.. pytest -q tests/test_opensearch_integration.py
```

The integration tests are skipped unless the URL is set. The rest run against an in-process fake cluster.
