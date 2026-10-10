# IMD-001: Immersive Discovery Architecture ADR

## Objective

Create `docs/adr/ADR-IMD-001-immersive-discovery.md`. Record the approved
decision to build the Roblox-like immersive discovery vertical as independent
API and web deployables over shared platform contracts, with fictional or
explicitly licensed data and local-only initial evidence.

## Dependencies

- OS-088 completion is recorded in
  `docs/execution/enterprise-search/OS-080-088-operations-review.md`, and the
  canonical OpenSearch plan status reports local implementation through
  OS-088. Production sign-off is not required for this local planning task.

This task may run concurrently with IMD-002.

## Read First

1. `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`
2. `docs/adr/ADR-OS-001-opensearch-enterprise-search.md`
3. `docs/ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md`
4. `docs/execution/enterprise-search/OS-080-088-operations-review.md`
5. `README.md`
6. `docs/architecture.md`
7. `packages/platform_contracts/__init__.py`

Do not read unrelated repository files.

## Owned Files

- Create `docs/adr/ADR-IMD-001-immersive-discovery.md`.
- Do not edit application, test, dependency, configuration, or deployment
  files.

## Required ADR Sections

1. Status and date.
2. Context and product outcome.
3. Decision and separate deployable boundaries.
4. Shared platform versus immersive-domain ownership.
5. Canonical data, derived index, event-lake, feature, and model authority.
6. Multi-stage retrieval and ranking flow.
7. Safety, age, consent, privacy, creator exposure, and audit constraints.
8. Synthetic and optional public-data policy.
9. LLM responsibilities and deterministic fallback.
10. Alternatives: extend support API, three separate platforms, generic
    one-ranker platform, and shared platform with domain profiles.
11. Local rollout and evaluation gates.
12. Deferred production, cloud, real-data, and billion-scale decisions.
13. Conditions that reopen the decision.

## Non-Negotiable Decisions

- Product code starts under `services/discovery-api` and
  `apps/discovery-web`.
- Discovery does not import support or analytics domain code.
- OpenSearch is a derived, rebuildable index; PostgreSQL/source systems remain
  authoritative.
- Checked-in data is fictional. Any public adapter requires provenance and
  explicit licensing review.
- An LLM cannot alter hard eligibility filters or become the online ranker of
  record.
- No live model, external data download, cloud deployment, or production claim
  is in scope.

## Acceptance Evidence

- ADR fixes separate deployables and the shared-contract boundary.
- It assigns clear authority for catalog, events, features, indexes, models,
  policies, and audit evidence.
- It records the no-scraping rule and synthetic-data limitations.
- It compares all required alternatives and explains the selected tradeoff.
- It links to the canonical plan and OpenSearch ADR.
- It does not claim implementation or production readiness.
- `git diff --check` passes.

## Stop Conditions

Stop and report without editing other files if:

- OS-088 or the OpenSearch architecture decision is absent;
- an existing ADR already assigns immersive discovery to a current product API;
- fulfilling the packet would require deciding public-data licensing or a cloud
  deployment.

## Targeted Validation

```bash
git diff --check
```

## Commit

```text
docs(discovery): IMD-001 record immersive architecture
```
