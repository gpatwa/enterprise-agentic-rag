# OS-001: OpenSearch Architecture ADR

## Objective

Create `docs/adr/ADR-OS-001-opensearch-enterprise-search.md`. Record the
approved decision to use OpenSearch for enterprise retrieval while preserving
PostgreSQL/object storage authority, Neo4j graph ownership, and Qdrant as a
migration fallback.

## Dependencies

None.

## Owned Files

- Create `docs/adr/ADR-OS-001-opensearch-enterprise-search.md`.
- Do not edit application, deployment, dependency, or configuration files.

## Required ADR Sections

1. Status and date.
2. Context and current baseline.
3. Decision.
4. Authority and data-flow boundaries.
5. Alternatives: Qdrant-only, Elasticsearch, Azure AI Search, pgvector, and
   Turbopuffer.
6. Consequences and tradeoffs.
7. Migration and rollback strategy.
8. Security and tenant-isolation constraints.
9. Hosting decision deferred to OS-053.
10. Conditions that would reopen the decision.

## Non-Negotiable Decisions

- OpenSearch is a derived, rebuildable index.
- Product code depends on `EnterpriseSearchProvider`, not OpenSearch payloads.
- Shared indexes require mandatory tenant and ACL filters.
- Qdrant remains until OS-089.
- This task does not select or deploy an Azure hosting model.

## Acceptance Evidence

- The ADR covers every required section.
- It does not claim implementation is complete.
- It links to the canonical execution plan.
- `git diff --check` passes.

## Stop Conditions

Stop and report instead of editing other files if the plan's executive decision
has changed or another ADR already claims a conflicting search backend.

## Commit

```text
docs(search): OS-001 record OpenSearch architecture decision
```
