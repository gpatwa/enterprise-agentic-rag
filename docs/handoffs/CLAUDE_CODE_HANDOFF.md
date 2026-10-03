# Claude Code Handoff

Updated: 2026-10-03

This is the durable project handoff between Claude Code sessions (originally
written by the Codex task, last updated after ADS-040/041/042/044). Re-check
repository state before acting; the information below records the verified
state at the time of writing, not an instruction to force the tree to match it.

## Verified Repository State

- Repository: `gpatwa/enterprise-agentic-rag`
- Branch: `claude/agentic-data-stack-continue-3be90b`, tracking
  `origin/claude/agentic-data-stack-continue-3be90b` (pushed; clean at handoff).
  It is based on `codex/ea-001-canonical-fixtures` (`9278e84`), **not** on `main`:
  `main` lacks all ADS work. A PR for this branch has not been opened.
- Latest commit: `d97c428 feat(analytics): add ADS-042 evidence envelope and
  append-only chain; allow timestamp_trunc in gateway validation`.
- Work happens in a git worktree; the worktree path can be recycled between
  sessions. Commits on the branch are the source of truth, not any one checkout.
- The user prefers completed milestones/packets to be committed and pushed; check
  the staged scope and upstream first. Do not run `ruff check --fix` over whole
  directories (it re-sorts unrelated files, e.g. an alembic migration); fix only
  the files you changed.

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
- **M4:** in progress. Wave 4A, 4B (through ADS-042) are implemented and all in
  manifest status `review`. **Nobody has independently reviewed them; do not mark
  them `complete` without the user's/reviewer's approval.**
  - **ADS-040** read-only DuckDB/PostgreSQL gateways (`app/execution/`).
    DuckDB is real and embedded; **PostgreSQL has only been tested against a
    recording fake engine, never a server**.
  - **ADS-044** `ContextRefreshWorker` (`app/context/refresh.py`): incremental
    refresh, tombstones, failure/last-good, staleness, ontology source,
    `SnapshotOntologyProvider`, snapshot selection/pinning at run start
    (`app/runtime/run_start.py`), ontology nodes in the OpenSearch index. HTTP and
    OpenSearch are faked (httpx MockTransport, in-memory index fake).
  - **ADS-041** result validation (`app/execution/result_validation.py`,
    `app/runtime/result_stage.py`): truncation, shape, grain, sort/limit, fanout,
    missing groups, invalid totals, fingerprints, control-query reconciliation.
  - **ADS-042** `EvidenceEnvelope` (`packages/platform_contracts/evidence.py`),
    builder, and append-only per-tenant hash-chained `EvidenceStore`
    (`app/runtime/evidence*.py`, migration `0004_evidence_envelopes`).
  - **ADS-043** grounded explanation + visualization spec
    (`app/execution/explanation.py`, `app/runtime/explain_stage.py`): claims cite fixed
    cell/semantic IDs, numbers must come from cited cells, one repair attempt, else
    evidence-only; result fingerprint is checked unchanged. Scripted explainers only; no
    real model client. Packet: `ADS-043-grounded-explanation.md`.
  - **ADS-045** governed v2 API (`app/api_v2.py`, `app/runtime/analyze_service.py`,
    `packages/platform_contracts/analytics_v2_api.py`): `POST /api/v2/analytics/analyze`
    (Idempotency-Key), `GET .../runs/{id}`, `POST .../runs/{id}/clarify`, `POST
    .../runs/{id}/review`; OIDC bearer identity, tenant+purpose scoping, outcomes map to
    the existing `AnalyticsV2Outcome` union (answer gained claims/result/visualization).
    **Mounted but inert**: 503 until `app.main.v2_runtime` gets a service and verifier;
    nothing in production wires them yet. Packet: `ADS-045-analyze-api.md`.
  - **ADS-046** v1 shadow adapter (`app/runtime/shadow.py`, wired into the v1 `/query`
    route, inert by default): v1 response returned unchanged; governed analysis stops at an
    estimated plan (blocked `approve/execute/result_validate/explain`, no review creation);
    privacy-safe comparison record to a sink. Results are not compared. Packet:
    `ADS-046-v1-shadow-adapter.md`.
  - **Next:** ADS-047 (evidence-first web workflow, wave 4C remainder); wave 4D:
    048, 049, then the M4 `local_demo_review` human gate.
  - **Known unwired seams (intentional, owned by later packets):** nothing calls
    `new_governed_run_state`, `record_terminal_evidence`, or the control-total
    builder in a production path yet (ADS-045 owns API/worker wiring; the control
    compile must reuse the primary compile's policy values, which `PolicyValueStore`
    pops one-time). The `result_validate` and `explain` nodes in the ADS-039 test
    graph are still stubs there. Cost units differ per dialect and are uncalibrated
    against run budgets. `fake_execution_node` keeps its name and
    `fake_execution_failed` code while accepting real gateways.
- **M5–M7:** planned.
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
- Execution: `app/execution/` (gateways, validation, bridge, result validation);
  compilers in `app/compiler/` (`DuckDBCompilerAdapter`; `CompiledQuery.dialect`).
  Refresh/context: `app/context/refresh.py`, `app/context/index.py`
  (`search_ontology`, additive mapping update). Run bootstrap pinning:
  `app/runtime/run_start.py`. Evidence: `app/runtime/evidence.py`,
  `app/runtime/evidence_store.py`.
- Analytics web product: `apps/analytics-web/`.

## Last Verification Evidence

At commit `d97c428`, run from `services/analytics-api`:

- `PYTHONPATH=.:../.. pytest -q` (equivalently `make test-analytics`): **309
  passed** (210 at the start of this workstream; +99 across ADS-040/041/042/044
  and the ontology/selection/indexing follow-ups).
- `ruff check packages/platform_contracts services/analytics-api/app
  services/analytics-api/tests`: all checks passed. `git diff --check` clean.
- After ADS-043 (uncommitted-tree run before its commit): `make test-analytics` **321
  passed** (+12 in `test_ads043_grounded_explanation.py`); after ADS-045 **330 passed** (+9 in
  `test_ads045_analyze_api.py`); after ADS-046 **339 passed** (+9 in `test_ads046_shadow.py`); focused `ruff check`/`format
  --check` and `git diff --check` clean.
- New suites: `test_ads040_execution_gateways.py`, `test_ads041_result_validation.py`,
  `test_ads042_evidence_envelope.py`, `test_ads044_context_refresh.py`,
  `test_ads044_ontology_index.py`. Some import helpers from other test modules
  (pytest rootdir import mode); keep that in mind when moving files.
- A real end-to-end graph-v2 run (DuckDB through the gateway, result validation,
  evidence sealing) is in `test_ads042_evidence_envelope.py`; it caught one real
  ADS-040 bug (the gateway rejected `DATE_TRUNC`/`TIMESTAMP_TRUNC`), now fixed.
- **Not performed (separate gates needing explicit user authorization):** live
  PostgreSQL, live OpenSearch, live OpenMetadata/dbt, any warehouse, any Azure
  deployment or cloud mutation.

Re-run relevant checks after new edits; do not reuse these results as evidence
for later work.

## Open Gates and Decisions for the User

- Independent review of ADS-040 to ADS-046 (manifest `review` → `complete`).
- M1 human semantic certification (still pending; nothing here certifies any
  ontology or contract).
- Live validation of PostgreSQL, OpenSearch, and catalog providers.
- Whether to open a PR from this branch and against which base (`main` lacks the
  ADS history).
- Later human gates: M4 `local_demo_review`, then M5-M7 gates per the manifest.

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

> Read `CLAUDE.md` and `docs/handoffs/CLAUDE_CODE_HANDOFF.md` first. Then verify
> `git status -sb`, the current branch and upstream (expect
> `claude/agentic-data-stack-continue-3be90b`, tip `d97c428` or later), and recent
> commits; treat the handoff as a snapshot and the repository as the source of
> truth. If the branch is missing the ADS history, check out
> `origin/claude/agentic-data-stack-continue-3be90b`.
>
> Continue the Agentic Data Stack from its canonical plan and manifest
> (`docs/AGENTIC_DATA_STACK_EXECUTION_PLAN.md`,
> `docs/execution/enterprise-analytics/agentic-data-stack-program.yaml`). M3 and
> ADS-039 are complete. ADS-040, 041, 042, and 044 are implemented and in `review`
> (no independent review yet; do not mark them complete). M1 human semantic
> certification and all live validation (PostgreSQL, OpenSearch, OpenMetadata/dbt)
> are separate pending gates: do not infer approval or claim they passed.
>
> Next unblocked packet: **ADS-043** (grounded explanation and visualization-spec
> node; claims must cite fixed result/semantic IDs and a repair step must not alter
> the result). Read its acceptance criteria in the plan, inspect the current code
> (`app/execution/result_validation.py`, `app/runtime/result_stage.py`,
> `app/runtime/evidence.py`), and implement only that bounded scope. Wave 4C
> (ADS-045+) waits on it.
>
> Keep validation local with fake providers unless I explicitly authorize live
> integrations or deployment. Do not deploy to Azure or mutate cloud resources.
> Preserve unrelated work, add tests, write the packet doc
> (`docs/execution/enterprise-analytics/ADS-043-*.md`), update the manifest status
> to `review` and this handoff, and run `make test-analytics`, `ruff check` on
> changed files only, and `git diff --check`. Report what changed, commands run,
> actual results, and remaining gates. Commit and push each completed packet after
> checking the staged scope and upstream.
