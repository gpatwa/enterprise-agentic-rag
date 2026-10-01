# Claude Code Handoff

Updated: 2026-09-30

This is the durable project handoff from the Codex task. Re-check repository
state before acting; the information below records the verified state at the
time of writing, not an instruction to force the tree to match it.

## Verified Repository State

- Repository: `gpatwa/enterprise-agentic-rag`
- Working directory: `/Users/gopalpatwa/opt/scalable-rag-pipeline`
- Branch: `codex/ea-001-canonical-fixtures`
- Upstream: `origin/codex/ea-001-canonical-fixtures`
- Latest commit: `d683e10 execute ADS-039 graph adversarial corpus`
- At handoff creation, the tree was clean and the branch matched its upstream.
- The user prefers completed milestones to be committed and pushed. This
  handoff itself is a repo change; verify whether it has been committed/pushed
  before assuming it is on GitHub.

## Product and Strategy Context

Compass is a monorepo containing independently deployable products with shared
versioned platform contracts:

1. **Resolution Intelligence** turns support tickets and knowledge into
   searchable resolution memory, evidence-backed answers, reviewed agent
   commands, and audit history. Its API/web app and RAG implementation are
   separate from Analytics.
2. **Analytics / Agentic Data Stack** is a separate product for governed,
   high-quality data access for AI: ingest/contextualize data, resolve meaning
   against a certified ontology, plan and compile deterministic queries,
   enforce policy and budgets, require human approval when needed, execute,
   and preserve evidence.
3. **Immersive Discovery** is a separately scoped Roblox-like search,
   recommendation, and personalization vertical, with its own plan and
   deployable boundary.

Keep one monorepo, separate products/deployables, and shared contracts. Do not
reintroduce Analytics into the support API. The high-level README contains
older umbrella descriptions; for Analytics graph behavior, prefer its current
runtime code and the Agentic Data Stack execution plan.

The longer-term product thesis is vertical, workflow-completing agent systems:
messy inputs become grounded decisions and permitted actions, with explicit
trust controls, human review, and auditability. Avoid generic AI wrappers and
do not conflate the three verticals into one undifferentiated agent.

## Agentic Data Stack State

Canonical task status is in
[`agentic-data-stack-program.yaml`](../execution/enterprise-analytics/agentic-data-stack-program.yaml).

- **M0:** complete; architecture/security approval recorded.
- **M1:** tasks ADS-010–019 are marked complete, but the milestone is still
  `in_progress` because its **human semantic-certification gate is pending**.
  Do not claim M1 is fully signed off or self-certify business semantics.
- **M2:** complete; threshold-and-harness review approved on 2026-09-24.
- **M3:** complete; graph-and-policy human review was approved on 2026-09-28.
  ADS-039's 15-scenario local graph-v2 corpus passed. ADS-039 fixed a real bug:
  resumed progress after an approval now changes persisted run status back to
  `active`.
- **M4–M7:** planned. The next M4 wave in the manifest is ADS-040 (PostgreSQL
  and DuckDB read-only gateway/compiler adapters) and ADS-044 (metadata refresh
  and context snapshot publication). Respect M1 certification and external
  integration gates while implementing; don't activate production paths by
  implication.
- **Live OpenSearch validation:** still separate external follow-up. ADS-039
  uses injected local fake search and execution providers; it did not contact
  OpenSearch or a warehouse.
- **Enterprise Search readiness:** implementation packets OS-001–OS-088 are
  tracked separately from Analytics. Live OpenSearch integration evidence,
  production TLS/backup drills, and operational sign-off were identified as
  external follow-up; verify the current packet/plan before treating any as
  closed.
- **Azure:** no deployment is authorized by this handoff. The user has
  previously restricted a deployment task to staging; ask for explicit
  authorization before any cloud deployment or resource mutation.

## Analytics Architecture in the Current Code

- Cross-product contracts: `packages/platform_contracts/` (Pydantic).
- Semantic contracts/ontology: `services/analytics-api/semantic_registry/`
  and `services/analytics-api/app/semantic_registry/`.
- Context snapshots, bounded packs, and OpenSearch adapter: `app/context/`.
- Dialect-neutral `AnalyticalIntent`: `packages/platform_contracts/analytics_intent.py`.
- Typed graph runtime: `services/analytics-api/app/runtime/`; graph-v1 is the
  pinned historical harness, graph-v2 is the governed graph with retrieval,
  intent extraction, ontology resolution, clarification, certification,
  authorization, compilation, estimation, review, and execution stages.
- Durable run/review state: `app/runtime/control_store.py` and Alembic
  migrations. Process-local plan/value stores are explicitly demo-level; later
  packets own production durability.
- PostgreSQL is the first SQL adapter. DuckDB is intended for local/embedded
  lake-file analytics. OpenSearch is the enterprise context/search target.
- Analytics web product: `apps/analytics-web/`.

## Last Verification Evidence

At commit `d683e10`:

- `cd services/analytics-api && PYTHONPATH=.:../.. pytest tests/test_ads039_graph_adversarial.py -q` passed the 15 required scenarios.
- `make test-analytics` passed **210 tests**.
- Focused Ruff checks/formatting and YAML/diff checks passed for that milestone.
- No Azure deployment, live OpenSearch integration, or warehouse integration
  was performed as part of ADS-039.

Re-run relevant checks after new edits; do not reuse these results as evidence
for later milestones.

## Canonical Roadmaps and Product Docs

- Overall repo: [`README.md`](../../README.md),
  [`docs/architecture.md`](../architecture.md),
  [`docs/ROADMAP.md`](../ROADMAP.md)
- Agentic Data Stack: [`docs/AGENTIC_DATA_STACK_EXECUTION_PLAN.md`](../AGENTIC_DATA_STACK_EXECUTION_PLAN.md),
  [`docs/execution/enterprise-analytics/README.md`](../execution/enterprise-analytics/README.md)
- Architecture diagrams: [`docs/diagrams/README.md`](../diagrams/README.md)
- OpenSearch: [`docs/ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md`](../ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md),
  [`docs/execution/enterprise-search/README.md`](../execution/enterprise-search/README.md)
- Resolution Intelligence: [`docs/resolution-intelligence-architecture.md`](../resolution-intelligence-architecture.md),
  [`docs/PROSPECT_SUPPORT_CASE_STUDY.md`](../PROSPECT_SUPPORT_CASE_STUDY.md),
  [`docs/LLM_RESOLUTION_INTELLIGENCE_EXECUTION_PLAN.md`](../LLM_RESOLUTION_INTELLIGENCE_EXECUTION_PLAN.md)
- Immersive Discovery: [`docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`](../IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md),
  [`docs/execution/immersive-discovery/README.md`](../execution/immersive-discovery/README.md)
- Local demo/startup guidance: product READMEs and
  [`docs/LOCAL_DEMO_READINESS.md`](../LOCAL_DEMO_READINESS.md)

## Suggested Claude Code Resume Prompt

> Read `CLAUDE.md` and `docs/handoffs/CLAUDE_CODE_HANDOFF.md`, then verify
> `git status -sb`, current branch/upstream, and recent commits. Continue the
> Agentic Data Stack from its canonical execution plan and manifest. M3 and
> ADS-039 are complete; M1 semantic certification and live OpenSearch evidence
> remain separate gates. Identify the next unblocked packet(s), inspect their
> acceptance criteria and current code, and execute only that bounded scope.
> Keep validation local with fakes unless I explicitly authorize external
> integration/deployment. Preserve existing work, update packet/manifest and
> diagrams when appropriate, and report actual test evidence and remaining
> gates. Commit and push completed milestones.
