# ADR-OS-001: OpenSearch Enterprise Search Plane

Status: Accepted for greenfield pre-customer implementation
Date: 2026-08-22

## Context

Compass currently uses Qdrant for vector retrieval and a bounded Python BM25
implementation for support lexical search. The lexical path reads a limited
number of canonical PostgreSQL records into the API process, which is suitable
for a local demo but cannot be the enterprise search plane for large tenants,
high query volume, ACL-aware retrieval, personalization, or recommendation
candidate generation.

The product needs one provider-neutral retrieval contract that can support
exact terms, semantic similarity, hybrid ranking, filters, evidence, and
future ranking features. Canonical support records and lake objects must remain
authoritative and independently rebuildable.

## Decision

Use OpenSearch as the enterprise search plane for:

- BM25 lexical retrieval and exact-term matching.
- Dense and sparse vector retrieval.
- Hybrid candidate generation and first-stage ranking.
- Tenant, document ACL, status, source, time, and classification filters.
- Facets, aggregations, and recommendation candidate retrieval.

OpenSearch is a derived index. PostgreSQL, source helpdesks, and S3/ADLS or
other customer lake storage remain the systems of record. Neo4j remains the
relationship and knowledge-graph store. Compass owns the provider-neutral
query contract, policy scope, final ranking policy, evidence, and audit trail.

Qdrant is a temporary local/demo fixture during implementation. There is no
customer-facing backward-compatibility requirement and no obligation to retain
Qdrant as a production fallback. The new OpenSearch contract may replace the
legacy path directly after local validation.

Operational safeguards still apply: index writes remain idempotent, tenant and
ACL checks fail closed, and aliases provide rollback between index generations
when an index operation is incomplete or fails.

## Authority Boundaries

| Concern | Authority |
|---|---|
| Canonical support records and actions | PostgreSQL and source helpdesk |
| Raw documents and lake objects | Customer source, S3, ADLS, or equivalent lake |
| Searchable text, vectors, and derived rank fields | Rebuildable OpenSearch index |
| Entity and relationship graph | Neo4j |
| Identity, groups, and source permissions | Customer identity and source systems |
| Search scope and policy decision | Compass policy context |
| Search and recommendation event history | Compass event store, initially PostgreSQL |
| Query evidence and audit history | Compass append-only audit store |

No OpenSearch document is authoritative for customer data, identity, or policy.
An index can be deleted and rebuilt from canonical sources without changing
customer truth.

## Index and Isolation Rules

1. Every query requires a non-empty tenant scope; production code has no tenant
   default.
2. Every query applies tenant and document ACL filters before ranking.
3. Shared indexes are the default topology, with `tenant_id` and `acl_tokens`
   represented as mandatory fields.
4. A tenant registry may route regulated or very large tenants to dedicated
   indexes. This is an operational routing decision, not a new query contract.
5. Physical indexes are versioned and accessed through stable read/write aliases.
6. Embedding model, mapping, analyzer, content, permission, and ranking versions
   are stored with the indexed document or index metadata.
7. Indexing uses a durable outbox and idempotent worker. Request-path dual
   writes are not permitted.

## Alternatives Considered

| Alternative | Decision | Reason |
|---|---|---|
| Qdrant only | Not selected | Strong vector path, but it does not provide the target lexical, hybrid, ACL, and recommendation search plane. No compatibility adapter is required for the pre-customer launch. |
| Elasticsearch | Rejected | Comparable search capability, but the selected architecture uses OpenSearch and its open-source-compatible ecosystem. Adding Elastic-specific APIs would create the dependency this decision is intended to avoid. |
| Azure AI Search | Not selected as the primary backend | Strong Azure-managed option and a candidate for an Azure-specific adapter, but the product requires a provider-neutral multi-cloud search plane with direct control of mappings, hybrid ranking, and rollout behavior. |
| pgvector | Rejected as the enterprise search plane | Keeps vectors beside PostgreSQL, but would require Compass to build and operate the lexical, ranking, search lifecycle, and recommendation capabilities separately. |
| Turbopuffer | Rejected as the first primary backend | Attractive object-storage-native retrieval economics, but it is focused on first-stage retrieval and would still require Compass-owned enterprise indexing, policy, and ranking services. It remains a benchmark candidate. |

## Hosting Decision

This ADR does not select the operating model for OpenSearch. OS-053 will
compare managed AWS, Azure-operated/BYOC, residency, upgrade, backup, network,
and cost requirements. No cloud resource is created by this ADR or by OS-001.

## Consequences

Positive consequences:

- Exact-term and semantic retrieval use one enterprise search contract.
- Hybrid ranking, filters, aggregations, and candidate retrieval share one
  searchable document model.
- Index generations and aliases provide operational rollback without preserving
  the legacy Qdrant customer path.
- Canonical data and search indexes have clear ownership and rebuild behavior.
- Personalization can be added as Compass-owned ranking policy without putting
  user behavior or authorization logic in the search backend.

Costs and risks:

- OpenSearch becomes a stateful enterprise dependency with index, shard,
  capacity, upgrade, backup, and security responsibilities.
- A durable outbox, worker, backfill, reconciliation, and alias lifecycle are
  required before production cutover.
- A shared index makes fail-closed tenant and ACL filters non-negotiable.
- Search quality must be measured against the current Qdrant plus lexical
  baseline before any traffic migration.
- Cold-cache behavior, index lag, bulk throttling, and mapping changes require
  explicit operational controls.

## Greenfield Launch and Operational Rollback

1. Define the provider-neutral contract and golden corpus.
2. Build versioned mappings, aliases, durable indexing, and reconciliation.
3. Run OpenSearch in local integration mode and validate the target demo path.
4. Compare OpenSearch against the Qdrant plus lexical implementation offline
   for overlap, ranking, ACL results, latency, and failures.
5. Canary one design partner after human approval of relevance, security, and
   operations evidence.
6. Roll back failed index operations through aliases and a prior physical
   generation; do not treat Qdrant as a required customer rollback path.

## Revisit Conditions

Reopen this decision if any of the following becomes true:

- A design partner requires a managed search service that OpenSearch cannot
  satisfy under residency or procurement constraints.
- Measured filtered recall or p95 latency is materially below the agreed gate.
- Operating cost is materially worse than Qdrant plus the current lexical path.
- A customer requires a search capability that belongs in a different backend
  and cannot be isolated behind the provider contract.
- The product changes from first-stage enterprise retrieval to a lakehouse-native
  query service; that may justify a Databricks or Azure AI Search adapter.

## References

- [Enterprise Search and Recommendation OpenSearch Execution Plan](../ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md)
- [Resolution Intelligence Architecture](../resolution-intelligence-architecture.md)
- [Original Product Roadmap](../ROADMAP.md)
