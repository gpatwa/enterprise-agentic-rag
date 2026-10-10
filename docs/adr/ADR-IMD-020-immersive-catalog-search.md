# ADR-IMD-020: Immersive Catalog Search Strategy

Status: Accepted for local implementation
Date: 2026-08-24

## Context and Local Demo Goals

The immersive discovery vertical needs a searchable fictional experience
catalog for exact lookup, lexical relevance, semantic discovery, and
personalized candidate generation. Search must preserve tenant, locale, device,
age, safety, availability, and provenance constraints before any model score is
considered. The local demo must remain deterministic, rebuildable, and usable
when a live search or embedding service is unavailable.

This ADR refines the independent product boundary in
[ADR-IMD-001](ADR-IMD-001-immersive-discovery.md) and follows the enterprise
search decision in [ADR-OS-001](ADR-OS-001-opensearch-enterprise-search.md).
It does not claim Roblox implementation details, production scale, or access to
Roblox data.

## Decision

Use OpenSearch as the derived catalog search plane for the immersive product.
PostgreSQL or an approved catalog adapter remains the source authority for
experiences, creators, availability, policy state, and provenance. Generated
event files and approved media remain canonical in local data/object storage.
OpenSearch documents, vectors, and ranking fields are rebuildable projections;
they are never the catalog or policy authority.

The discovery service owns candidate-source orchestration, policy evaluation,
candidate fusion, final ranking, explanations, and fallback behavior. OpenSearch
owns first-stage exact, BM25, vector, filtered, and hybrid candidate retrieval.

## Index Generations, Aliases, and Recovery

Each mapping, analyzer, embedding contract, and index generation is named and
versioned, for example:

```text
imd-catalog-v{schema}-{embedding}-{generation}
imd-catalog-read
imd-catalog-write
```

The read and write aliases point to the active physical generation. A rebuild
creates a new generation from canonical catalog records, validates document
counts, versions, eligibility fields, and golden retrieval evidence, then
atomically moves the aliases. A failed or incomplete build leaves the active
generation untouched. Rollback moves the aliases to the prior validated
generation; it does not mutate canonical data.

Indexing is idempotent and carries content, permission, policy, embedding, and
generation versions. Deletes and tombstones are represented in the rebuild
input and cannot be inferred solely from the current index. Local evidence must
show a clean rebuild and alias rollback using generated data.

## Lexical and Exact Search Strategy

Use a versioned OpenSearch analyzer for title, description, tags, genres, and
creator display text. The default lexical path is BM25 over analyzed fields,
with field weighting that favors title, tags, and exact normalized phrases over
long descriptions. Keep a normalized keyword field for exact matching.

Exact experience IDs, creator IDs, and other stable identifiers use keyword
queries and are evaluated before broad lexical matching. Title phrase matches
receive a deterministic boost. Query text is normalized for case and harmless
Unicode variation, but identifiers are never stemmed or fuzzily rewritten.
Lexical retrieval returns candidate evidence such as matched fields and phrase
signals; it does not decide final personalized order.

## Vector Strategy

The initial embedding contract is configuration- and contract-versioned:

```text
embedding_model_version = imd-text-embedding-v1
vector_dimensions = 384
similarity = cosine
index_schema_version = imd-catalog-schema-v1
```

The model version, dimensions, similarity, normalization rule, and input
projection fields are recorded in index metadata and every indexed document.
Changing any of them requires a new physical index generation and rebuild; a
mixed-dimension generation is invalid. The local implementation may use a
deterministic fake embedding provider for repeatability, but fake vectors must
carry the same explicit contract metadata.

Use OpenSearch approximate nearest-neighbor search with HNSW and a bounded
candidate count. The initial local configuration is a documented starting
point, not a production capacity claim: cosine similarity, HNSW `ef_search`
and `ef_construction` kept in versioned index configuration, and `m` selected
for the local corpus. These settings can be tuned only through a new indexed
configuration/version and measured evidence.

Tenant, locale, device, age, safety, availability, consent, and blocked-item
filters are hard pre-score filters on vector, lexical, and hybrid queries.
Similarity thresholds and model scores cannot reintroduce an ineligible item.

## Required Indexed Fields

Every catalog document must carry fields sufficient for filtering, evidence,
rebuild, and diversity:

| Group | Required fields |
|---|---|
| Identity | `experience_id`, `creator_id`, `tenant_id` |
| Search text | normalized ID, title, description, tags, genres, themes |
| Eligibility | locale, supported devices, age rating, safety state, availability, blocked state |
| Provenance | source type, source ID, license/provenance reference, content version |
| Freshness | created time, updated time, freshness bucket, catalog generation |
| Discovery signals | quality/versioned aggregate signals, cold-start state, embedding model/version |
| Diversity | creator ID, genre/theme facets, modality, repetition/exposure keys |

User and request context remains request-scoped. Sensitive history, raw query
text, and full embeddings do not belong in ordinary logs or checked-in
fixtures. User profile and consented behavior features are versioned derived
inputs to discovery ranking, not authority fields in the catalog index.

## Retrieval and Final Ranking Ownership

The request path is:

```text
request context and hard eligibility filters
  -> exact/BM25 candidates and vector candidates
  -> optional social, co-play, trending, and cold-start candidates
  -> deterministic fusion and deduplication
  -> discovery pre-rank and final rank
  -> safety, diversity, freshness, and creator policy re-rank
```

OpenSearch is responsible for exact, BM25, vector, filtered, and hybrid
candidate retrieval. The discovery service is responsible for source quotas,
fusion, behavioral features, personalization, multi-stage ranking, reason
codes, diversity, freshness, creator exposure, and final policy enforcement.
An LLM, if added later, may interpret a query or enrich fictional metadata but
cannot change hard filters or become the authority for final eligibility.

## Alternatives

| Alternative | Decision | Reason |
|---|---|---|
| Qdrant | Not selected | Useful for vector retrieval, but it does not provide the chosen combined lexical, exact, filtered, and hybrid catalog search plane. |
| pgvector | Not selected | Keeps vectors near source data but would require building and operating the lexical, hybrid, alias, and candidate-search lifecycle separately. |
| Elasticsearch | Not selected | Comparable capability, but the platform has already selected OpenSearch and its compatible ecosystem for the search contract. |
| Azure AI Search | Deferred | A possible managed adapter for a later hosting decision; this local ADR must not select cloud hosting or residency. |
| Object-storage-native vector search | Deferred | May be attractive at large scale, but does not replace the initial lexical, exact, filtered, and hybrid search plane without additional services. |

## Local-Only Rollout and Evidence Gates

This ADR authorizes no cloud deployment, external catalog download, live model
call, or Roblox scraping. Use fictional deterministic catalog fixtures and a
recorded generator seed. Synthetic catalog, events, embeddings, mappings, and
index generations must be versioned in manifests so the index can be deleted
and rebuilt reproducibly.

Local evidence gates are:

1. exact ID, phrase, BM25, vector, and hybrid golden cases pass;
2. all mandatory filters are applied before scoring and no cross-tenant result
   is returned;
3. alias-based rebuild and rollback preserve the prior active generation;
4. document and embedding versions are visible in normalized evidence;
5. deterministic fake providers allow the demo to run without live OpenSearch
   or embeddings, while local OpenSearch evidence is recorded when available.

## Billion-Scale Reopen Conditions, Costs, and Risks

No billion-item capacity, cost, or latency claim is made. Reopen the strategy
only after measured corpus size, vector dimensions, filtered recall, p95/p99
latency, shard/replica sizing, ingestion rate, storage growth, backup time, and
regional/residency requirements are known. The comparison must include managed
OpenSearch, operated OpenSearch, a dedicated vector backend, and a lakehouse or
object-storage-native design.

Relevant risks are HNSW memory pressure, shard imbalance, filter selectivity
reducing ANN recall, embedding-generation migration cost, index rebuild duration,
alias mistakes, stale catalog state, and operational cost of replicas and
backups. These are measurement and operations concerns, not reasons to make a
future hosting decision in this local ADR.

## Conditions That Reopen the Decision

Reopen this ADR if measured local evidence fails the agreed recall or latency
gates, if a design partner requires a managed or residency-constrained service
OpenSearch cannot satisfy, if catalog authority or privacy requirements change,
or if billion-scale measurements show that the selected index topology is
materially uneconomic. Reopening must preserve the provider-neutral discovery
contract and the separation between retrieval, eligibility, and final ranking.

## References

- [Immersive Discovery Architecture](ADR-IMD-001-immersive-discovery.md)
- [OpenSearch Enterprise Search Plane](ADR-OS-001-opensearch-enterprise-search.md)
- [Immersive Discovery Execution Plan](../IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md)
- [OpenSearch Execution Plan](../ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md)
