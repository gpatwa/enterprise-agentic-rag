# IMD-020: Immersive Catalog Search and Vector Strategy ADR

## Objective

Record the initial local search strategy for the immersive catalog: versioned
OpenSearch mappings, exact/BM25 and vector retrieval, mandatory eligibility
filters, aliases, and the conditions that would justify a different backend at
billion-item scale. This task is documentation only.

## Dependencies

- IMD-001 is merged at `e5c679d`.
- IMD-004 is merged at `ad90e75`.
- The current branch contains the IMD-004 checkpoint.

## Read First

1. `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`
2. `docs/adr/ADR-IMD-001-immersive-discovery.md`
3. `docs/adr/ADR-OS-001-opensearch-enterprise-search.md`
4. `docs/ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md`
5. `docs/architecture.md`
6. `services/api/app/search/models.py`
7. `docs/execution/immersive-discovery/IMD-020-search-strategy-adr.md`

Do not read unrelated repository files or browse for a new backend.

## Owned Files

- Create `docs/adr/ADR-IMD-020-immersive-catalog-search.md`.

Do not edit mappings, provider code, dependencies, deployment, or configuration.

## Required ADR Sections

1. Status and date.
2. Immersive catalog search context and local demo goals.
3. Decision: OpenSearch as derived catalog search plane with PostgreSQL/source
   authority.
4. Index generation, read/write aliases, and rebuild/rollback boundaries.
5. Lexical analyzer and exact-ID/title/phrase strategy.
6. Vector strategy: versioned dimensions, embedding model contract, HNSW/ANN
   configuration, similarity, and hard pre-score filters.
7. Required fields for tenant, locale, device, age, safety, availability,
   provenance, freshness, and creator diversity.
8. Candidate retrieval versus final ranking ownership.
9. Alternatives: Qdrant, pgvector, Elasticsearch, Azure AI Search, and
   object-storage-native vector search.
10. Local-only rollout and evidence gates.
11. Billion-scale reopen conditions, costs, and operational risks.
12. Conditions that reopen the decision.

## Non-Negotiable Decisions

- OpenSearch is derived and rebuildable; it is not catalog or policy authority.
- Tenant, age, safety, locale, device, availability, and blocked-item filters
  apply before model score or ranking.
- Mapping, analyzer, embedding, and index generations are versioned.
- Retrieval is first-stage candidate generation; immersive policy and final
  ranking remain in the discovery service.
- The initial vector dimension/model is configuration and contract versioned,
  not hidden in provider payloads.
- No cloud deployment or billion-scale claim is made by this ADR.

## Acceptance Evidence

- ADR covers every required section and links to IMD-001 and OS-001.
- It chooses a coherent local strategy without hardcoding a future production
  hosting decision.
- It explicitly separates exact/BM25, vector retrieval, eligibility, and final
  ranking responsibilities.
- It states how synthetic data and embeddings are versioned and rebuilt.
- `git diff --check` passes.

## Stop Conditions

Stop if an existing ADR conflicts with OpenSearch as the selected search plane,
if the task would require a cloud deployment decision, or if the vector model
dimension cannot be stated as a versioned configuration contract.

## Targeted Validation

```bash
git diff --check
```

## Commit

```text
docs(discovery): IMD-020 record catalog search strategy
```

