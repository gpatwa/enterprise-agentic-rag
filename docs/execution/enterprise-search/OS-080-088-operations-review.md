# OS-080 to OS-088 Security and Operations Review

## Verified locally

- tenant and ACL filters are compiled as provider-owned clauses and are
  rechecked on normalized responses;
- audit attributes contain operation, tenant, generation, outcome, and count,
  never query text, ticket text, or embeddings;
- interaction events require consent, have bounded retention, and support
  idempotent writes plus tenant deletion;
- TLS, credentials, and least-privilege requirements are documented in the
  deployment contract;
- alias generations, bounded workers, rollback controls, and local restore
  commands are documented;
- unit and provider-fake suites pass without requiring OpenSearch.

## Required live evidence

The following cannot be truthfully completed without starting a cluster and
receiving operator approval: TLS certificate rotation, snapshot restore timing,
cluster throttling recovery, production SLO burn-rate alerts, and a design
partner cutover. Azure deployment is not performed by this task.

## Local OpenSearch Evidence (2026-08-23)

- cluster health: green, one node, all primary shards active;
- provider integration test: passed against OpenSearch 2.15.0;
- golden corpus: 24 documents indexed, 12 queries evaluated;
- lexical Recall@10: `0.7083`; MRR: `0.7500`; NDCG@10: `0.6675`;
- ACL leaks: `0`; duplicate results: `0`;
- generation restore drill: `24 -> 24` documents in `76.95 ms`;
- alias rollback: `opensearch-integration-g2 -> opensearch-integration-g1` passed.

This is local evidence, not a production backup or TLS certificate drill.

## Review disposition

`CONDITIONALLY READY FOR LOCAL DEMO AND PILOT REVIEW`. There are no known
critical/high code findings in the local gates. Production approval remains
pending the live evidence above and product/security/operations signatures.
