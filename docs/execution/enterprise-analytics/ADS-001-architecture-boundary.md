# ADS-001: Architecture ADR and Product Boundary

Status: Review
Milestone: M0, Program and graph foundations
Owner: Architecture and platform

## Objective

Freeze the product, deployable, data-authority, trust, and deployment boundaries
for the Agentic Data Stack before graph runtime or semantic contracts are
implemented.

## Dependencies

- Existing enterprise analytics plan and split-product baseline
- Existing OpenSearch and support-resolution architecture decisions
- Archify-generated system and request diagrams

## Deliverables

- [ADR-ADS-001](../../adr/ADR-ADS-001-agentic-data-stack-boundary.md)
- Updated program and architecture references where needed

## Acceptance

- The ADR names legacy and target paths.
- Support search and enterprise analytics are separately deployable.
- PostgreSQL, DuckDB, OpenSearch, semantic registry, context, graph, policy,
  evidence, and audit authorities are explicit.
- Local and Azure-staging scope is explicit; production deployment is excluded.
- LLM authority and non-goals are explicit.
- Archify sources and generated diagrams remain valid.
- An independent architecture reviewer answers the review questions and records
  approval separately from the author.

## Validation

From the repository root:

```bash
make architecture-check
git diff --check
```

The standard analytics gate is also required for the integrated milestone:

```bash
ruff check packages/platform_contracts services/analytics-api/app services/analytics-api/tests
(cd services/analytics-api && PYTHONPATH=.:../.. pytest -q)
```

## Scope limits and stop conditions

Do not change runtime code, public API behavior, migrations, provider
dependencies, cloud resources, or generated diagram HTML by hand. Stop and
request architecture review if a later task requires combining support and
analytics into one runtime boundary or granting the LLM direct execution
authority.
