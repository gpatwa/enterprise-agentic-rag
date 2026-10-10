# Local OpenSearch Runbook

The OpenSearch plane is an opt-in local dependency. The default support demo
continues to use its existing local fixture when `OPENSEARCH_ENABLED=false`.

## Start and verify

```bash
docker compose --profile search up -d opensearch
curl --fail http://127.0.0.1:9200/_cluster/health
OPENSEARCH_INTEGRATION=1 pytest -m opensearch_integration services/api/tests
```

For the API path, provide `OPENSEARCH_ENABLED=true`,
`OPENSEARCH_URL=http://opensearch:9200`, and a matching embedding dimension.
The local profile disables the security plugin only inside the developer
network; production requires TLS and a least-privilege identity.

## Stop and reset

```bash
docker compose --profile search stop opensearch
docker compose --profile search down -v
```

The second command deletes the local derived index volume. PostgreSQL remains
the authority and can be reindexed after the reset.

## Evidence to capture

- cluster health and OpenSearch version;
- mapping compatibility result and active alias;
- golden-corpus relevance and ACL report;
- p50/p95/p99 query latency and bounded indexing throughput;
- rollback result proving the previous alias remains readable.
