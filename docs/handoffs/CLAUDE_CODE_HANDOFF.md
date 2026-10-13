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
  - **ADS-047** Governed view in `apps/analytics-web/src/governed/` (answer with
    browser-verified claims, clarify, review, refuse, failed, running, trace, read-only
    replay); `plan_fingerprint` added to the v2 review outcome. `npm test` (18) in
    `apps/analytics-web`. Packet: `ADS-047-evidence-first-web-workflow.md`.
  - **ADS-048** local reference stack, **fakes only** (`services/analytics-api/reference_stack/`):
    DuckDB journey plus a PostgreSQL journey through the real gateway against an emulated
    engine (no server); `make analytics-reference-smoke` / `analytics-reference-up`. Observed the
    uncalibrated cost-unit seam (default run budget rejects DuckDB scans); the stack sets an
    explicit budget. Packet: `ADS-048-local-reference-stack.md`.
  - **ADS-049** M4 golden suite and report (`reference_stack/golden.py`, pinned corpus, thresholds
    in `reference_stack/golden/m4-thresholds.json` (**approved by the user 2026-10-08**, scope: these
    local thresholds only; recorded in the manifest as `M4.m4_threshold_approval`); `make
    analytics-golden` writes `docs/execution/enterprise-analytics/reports/`). 28/28 executions
    pass and every approved gate is met, and the M4 `local_demo_review` gate was separately approved by the user on 2026-10-09 (limits recorded in the manifest); the
    suite is a pipeline-integrity check (scripted model, emulated PostgreSQL). Also fixed an
    ADS-045 bug (unusable snapshot caused HTTP 500). Packet: `ADS-049-m4-golden-report.md`.
  - **M5 started.** The user confirmed the first-packet proposal ("Go with your recommendations").
  - **ADS-050** structured feedback capture (`packages/platform_contracts/feedback.py`,
    `app/runtime/feedback_*.py`, `evidence_sealer.py`, migration `0005`,
    `POST /api/v2/analytics/runs/{id}/feedback`): append-only, bound to the sealed evidence envelope,
    corrections name certified semantic IDs only, recording only (no effect on goldens/policy/prompts).
    The v2 service now seals evidence at terminal. Backend/API only. Packet: `ADS-050-feedback-capture.md`.
    Suite: **365 passed**.
  - **ADS-051** deterministic feedback triage (`packages/platform_contracts/triage.py`,
    `app/triage/`, migration `0006`): nine-category taxonomy, 19 versioned rules, evidence outranks the
    reporter, notes never an input, append-only records, on demand, no endpoint. Corpus thresholds in
    `reference_stack/triage/triage-thresholds.json` were **approved by the user 2026-10-09** (scope: those
    thresholds only; `M5.m5_triage_threshold_approval`; the M5 human gate is still open). Packet:
    `ADS-051-feedback-triage.md`. Suite: **415 passed**.
  - **ADS-052** change proposals (`packages/platform_contracts/proposals.py`, `app/proposals/`, migration `0007`):
    closed operation list (flag a definition in a *draft* contract, request a context edge, flag a label
    collision), inert `proposed` data, append-only, the contract itself blocks anything but drafts. Corpus
    thresholds in `reference_stack/proposals/proposal-thresholds.json` were **approved by the user 2026-10-09** (scope: those thresholds only; `M5.m5_proposal_threshold_approval`).
    Packet: `ADS-052-semantic-context-proposals.md`. Suite: **451 passed**. The user confirmed the wave-5B plan
    ("go with your recommendations"): 053 next (fixture dbt project, approved-files allowlist, validation command
    never run), then 054 (immutable prompt/example candidate registry, references and fingerprints only).
  - **ADS-053** dbt docs/test proposals (`app/proposals/dbt_*.py`, fixture project
    `reference_stack/dbt_fixture/`): missing column descriptions (templated from the certified contract) and
    `unique`/`not_null` tests only, in approved `schema.yml` files; the contract rejects any other file or edit;
    validation commands are text and dbt is never run (tests patch process spawning to raise). Corpus
    thresholds in `reference_stack/dbt_proposals/dbt-thresholds.json` were **approved by the user 2026-10-09** (scope: those thresholds only; `M5.m5_dbt_threshold_approval`).
    Packet: `ADS-053-dbt-proposals.md`. Suite: **498 passed**.
  - **ADS-054** prompt/example candidate registry (`packages/platform_contracts/prompt_registry.py`,
    `app/prompt_registry/`, migration `0008`): append-only; released versions are write-once and only the system
    baseline can create one; a candidate's version is content-derived so it can never take a released version;
    prompts must keep the defensive clauses; examples hold references and fingerprints only. `intent-prompt@v1`
    is pinned to the runtime prompt by a drift test; **the runtime does not read the registry**. Corpus thresholds
    in `reference_stack/prompt_registry/prompt-thresholds.proposed.json` are **PROPOSED, NOT APPROVED**. Packet:
    `ADS-054-prompt-registry.md`. Suite: **520 passed**. This completes wave 5B.
  - **ADS-055** independent review workflow (`packages/platform_contracts/review.py`, `app/review/`, migration `0009`):
    append-only reviews and audit events; separation of duties enforced (automated identities, non-reviewers, the
    generator/creator, every feedback submitter, the requester, and repeat deciders cannot approve); a decision must name
    the exact content and the subject must be unchanged; 72h expiry (injectable clock) audited once; approving records a
    fact and applies/certifies/promotes nothing; no endpoint. Reviewer = `analytics-reviewer` group in the token. Corpus
    thresholds in `reference_stack/review/review-thresholds.proposed.json` are **PROPOSED, NOT APPROVED**. Packet:
    `ADS-055-independent-review.md`. Suite: **551 passed**. (Built on the ADS-054 branch; PR #24 must merge first.)
  - **ADS-056** candidate evaluation (`packages/platform_contracts/candidate_evaluation.py`, `app/evaluation_gate/`,
    migration `0010`): only subjects with an approved independent review of their exact content are evaluated; affected
    cases are selected deterministically from a pinned case index; targeted and full suites (golden, triage, proposals, dbt
    only, i.e. those with approved thresholds) run; verdicts rest on approved thresholds only and fail closed if a protected
    file changes; candidates are applied only in sandbox stacks (prompt via a new optional `prompt_builder` hook that
    defaults to the runtime prompt; review flags on a contract copy). Corpus thresholds in
    `reference_stack/evaluation/evaluation-thresholds.proposed.json` are **PROPOSED, NOT APPROVED**. Packet:
    `ADS-056-candidate-evaluation.md`. Suite: **571 passed**. (Stacked on the ADS-055 branch; PR #25 must merge first.)
  - **ADS-057** rollout controller (`packages/platform_contracts/rollout.py`, `app/rollout/`, migration `0011`; registry gained
    `release_promoted`/`next_release_version`; a released prompt may now be a recorded promotion): start needs an *approved*
    rollout policy, a human starter, an approved fresh review, a passing evaluation, and the candidate's parent still
    active; shadow then canary stages (each re-checks the gates) roll back automatically on failure; promote creates the next
    released version and appends the active pointer; rollback only appends (reverted pointer, event), deleting nothing.
    **The runtime reads none of it.** The shipped policy `reference_stack/rollout/rollout-policy.proposed.json` is
    **PROPOSED, NOT APPROVED**, so the controller refuses to run until the user approves it; corpus thresholds in
    `reference_stack/rollout/rollout-thresholds.proposed.json` are also proposed. Packet: `ADS-057-rollout-controller.md`.
    Suite: **585 passed** (about 4.5 min). Stacked on the ADS-056 branch. **This completes wave 5C.**
  - **ADS-058** drift monitors (`packages/platform_contracts/drift.py`, `app/drift/`, six runbooks under
    `docs/execution/enterprise-analytics/runbooks/`): ten rules over six monitors (context, retrieval, intent, outcomes,
    latency, cost) compare a current window of terminal runs with a baseline; too little data or a zero baseline is
    skipped and reported, never guessed. Observations hold numbers and codes only. **Advisory and read-only: an alert
    starts no rollback, and nothing in the runtime or API imports it.** The alert rules
    (`reference_stack/drift/drift-policy.proposed.json`) and corpus thresholds (`drift-thresholds.proposed.json`) are
    **PROPOSED, NOT APPROVED**. Packet: `ADS-058-drift-monitors.md`. `make analytics-drift-eval`: 18/18 cases.
  - **ADS-059** closed-loop safety and poisoning evaluation (`reference_stack/poisoning_eval.py`, 26-case pinned corpus,
    `make analytics-poisoning-eval`): hostile feedback, candidates, patches, approvals, and rollouts run against the real
    ADS-050..057 code; after the campaign protected files are byte-identical, the golden suite still meets its approved
    thresholds on both engines, the same question gives the same answer, no release/pointer changed, and no barred identity
    approved anything. It fails when a defence is weakened (tested). Thresholds in
    `reference_stack/poisoning/poisoning-thresholds.proposed.json` are **PROPOSED, NOT APPROVED**; this is not the M5
    `separation_of_duties_review` and not an independent review. Collusion between two real reviewers is out of scope.
    Packet: `ADS-059-poisoning-evaluation.md`. **This completes wave 5D (all of M5's packets are now implemented, in `review`).**
  - **ADS-060** versioned agent tool surface (`packages/platform_contracts/agent_tools.py`, `app/agent_tools/`; M6 wave 6A): five
    strict tools (analyze, status, clarify, review, evidence) over the same `GovernedAnalyzeService` as REST; `analytics.review`
    is human-only (automated, `agent:`/`system:`/`service:`/`model:`, and delegated-claim identities are refused); evidence is a
    data-free summary with the chain position; schemas are pinned by `catalogue.lock.json` and a generated catalogue doc. No
    transport or endpoint yet (ADS-061 is the MCP adapter). Packet: `ADS-060-agent-tool-surface.md`.
  - **ADS-062** portable analysis artifact (`packages/platform_contracts/analysis_artifact.py`, `app/analysis_artifacts/`): a content-addressed
    record of one finished run (answer/claims/visualization/result shape plus a rows hash/semantic IDs/sealed-evidence pointer); rows
    are opt-in and never change the ID; volatile and sensitive fields are excluded; REST, the ADS-060 tool surface, and the service
    produce the same artifact and view; 13 tamperings are rejected; verifiable against the live evidence chain. No transport yet.
    Packet: `ADS-062-analysis-artifact.md`.
  - **ADS-063** identity and delegated-purpose policy (`app/security/identity.py`, `packages/platform_contracts/delegation.py`,
    hardened `app/security/oidc.py`; `V2Runtime.resolver`): token claims are strictly validated (a 30-case issuer-agnostic negative suite;
    **12 of the 30 were accepted by the previous verifier**, including disagreeing `tid`/`tenant_id`); groups are intersected with a
    directory on every request so a removal takes effect on the next call; a delegated (`act`) token gets only the intersection of the
    person's and the agent's purposes and groups, requires an **approved** delegation policy (the shipped one is PROPOSED, so delegation
    is off), and is an agent call that can never decide a review (now also enforced on REST). Local issuer only: the "real IdP" suite
    is not run. Packet: `ADS-063-identity-delegation.md`. **This completes wave 6A.**
  - **ADS-061** MCP adapter (`app/mcp/`, `app/agent_tools/audit.py`): a JSON-RPC 2.0 subset (initialize, ping, tools/list, tools/call) over the
    ADS-060 surface with **per-message authentication** through the identity resolver and an append-only hash-chained audit of every
    tool call on every transport (argument digests only). It imports only the tool surface and identity layers (tested). stdio line
    framing only; no HTTP/SSE transport. Packet: `ADS-061-mcp-adapter.md`.
  - **ADS-064** customer data-plane protocol and VPC-boundary simulator (`packages/platform_contracts/data_plane.py`, `app/data_plane/`): a
    signed (HMAC, fresh, replay-proof) control-path protocol whose messages **cannot carry rows or credentials**; the data-plane agent
    holds the warehouse credential, executes, **validates locally (ADS-041)**, and returns metadata plus a verdict; rows go only to the
    requesting person from the data plane with their own token; a boundary scanner **blocks and records** leaks (a leaking agent is
    detected in tests). A simulator, not isolation; **graph integration (remote result stage, withheld-rows answer) is not done**.
    Packet: `ADS-064-data-plane.md`.
  - **ADS-065** observability (`app/observability/`): one trace per run (trace ID derives from the run) across API, graph, context, gateway, and
    evidence via proxies; allow-listed span attributes and metric labels, a pattern redactor, `run_ref` correlation, capped label
    cardinality, Prometheus text; nothing sensitive in exported telemetry (tested). In-memory only; not mounted; the data-plane agent is
    not instrumented. Packet: `ADS-065-observability.md`. **This completes wave 6B.**
  - **ADS-066** per-tenant quotas, SLOs, cost attribution, alerts (`app/quotas/`, `packages/platform_contracts/quotas.py`): token-bucket rate limit, concurrency
    cap, daily cost budget (resets 00:00 UTC), cost attributed once per run from sealed evidence, deduplicated alerts, two-window SLO burn
    rates; admission happens before any query runs; a deterministic load simulator (reused by ADS-076). The policy is **PROPOSED**; state is
    in-memory (HA is ADS-068); not mounted. Packet: `ADS-066-quotas-slos.md`.
  - **ADS-067** threat model + security suite (`docs/.../security/threat-model.md`, `reference_stack/security_eval.py`, 28-case corpus, `make analytics-security-eval`):
    22 threats each tied to real tests (a test checks the references exist); hostile model/explainer/injection/tenant/token/inference cases; **a findings
    register F-01..F-06**. Real defects found and fixed: unbucketed-timestamp and grain-key grouping (row-level access), run IDs derivable by a colleague
    (optional HMAC `run_id_key`, a deployment requirement), empty results failing as internal errors, and **host-time-zone-dependent time ranges** (gateways now pin UTC).
    New optional `min_cohort` (off by default). **F-03 (small cohorts/differencing) is an OPEN DECISION for the data/security owners** (rated high in general, medium at
    pilot scope); nothing here is an independent security review. Packet: `ADS-067-threat-model-security-suite.md`.
  - **ADS-068** resilience (`app/resilience/`, `reference_stack/resilience_eval.py`, pinned checkpoint fixtures, `make analytics-resilience-drill`): verified logical backup/restore
    (refuses corrupt/tampered/wrong-schema/non-empty, atomic, re-verifies digests and every evidence chain), a restore drill measuring RPO/RTO against **PROPOSED** objectives
    (RPO 15m, RTO 15m, lease 30s), a lease-takeover failover drill (query runs once; zombie fenced), upgrade-with-data and mixed-worker tests, and checkpoint fixtures as the
    release-to-release compatibility contract. Fixed: a restart/restore made old answered runs raise a 500. **Not restored (decisions for the owners): answer rows, compiled plans, policy
    values (process-local), so a run paused for review before a restart fails closed.** Local only; no real HA or production recovery tested. Packet: `ADS-068-resilience.md`.
  - **ADS-069** operations dashboard and runbooks (`app/operations/dashboard.py`, `packages/platform_contracts/ops_dashboard.py`, `reference_stack/operations_eval.py`, `make analytics-operations-drill`):
    read-only dashboard over quota/SLO/drift alerts, 12 release-gate evidence files (status echoed from the file; **it never records or infers an approval**), and open security findings;
    11 `ops-*` runbooks (every alert kind and gate resolves to one; a test checks sections); `diagnose_run` reads a run's durable path/terminal/evidence ids (no content, `run_ref` only); 7 seeded failures
    (cost budget, rate limit, SLO burn, latency, policy-refused run, corrupt backup, failing security gate) are diagnosed to the right runbook and replay with identical signatures. No new thresholds.
    Local only; the dashboard is a library and report, not a mounted UI. Packet: `ADS-069-operations.md`. **This completes wave 6C; the M6 gate `security_and_operations_review` is the user's.**
  - **ADS-070** reference corpus (`reference_stack/m7_corpus.py`, `reference_stack/m7/corpus-v1.json`, `corpus-approval.proposed.json`): 100 cases (60 answers, 30 marked P0 customer-style; 16
    refusals; 4 policy-denied; 4 tenant-isolation; 8 clarify; 8 review) with expected rows from an oracle that imports nothing from the system under test; pinned by digest. **Owner approval
    (definition owner and results owner, independently) is pending and is not recorded; the questions are phrasings of reference intents, not real customer questions.** Packet: `ADS-070-reference-corpus.md`.
  - **ADS-071** correctness and dialect equivalence (`reference_stack/m7_eval.py::run_correctness`, `m7/e2e-thresholds.proposed.json`, `make analytics-m7-correctness`): the ADS-070 corpus on DuckDB and emulated PostgreSQL;
    all twelve proposed gates met (200 case runs). Thresholds and corpus are **unapproved**; PostgreSQL is emulated and the model scripted. Packet: `ADS-071-correctness-equivalence.md`.
  - **ADS-072** retrieval evaluation (`reference_stack/retrieval_eval.py`, `m7/retrieval-*.json`, `make analytics-m7-retrieval`): 40 queries over a trap-laden catalogue through the real `OpenSearchContextIndex` adapter into
    an in-memory stand-in (term overlap, not BM25); six proposed gates met (top-3 recall, zero uncertified/foreign results, provenance, stale detection, -78% tokens vs whole-catalogue baseline, no overruns). Finding: the adapter's
    per-hit re-check keeps leaks at zero even when the backend ignores filters. Not measured: real ranking, live index, ADS-007 baseline. Packet: `ADS-072-retrieval-evaluation.md`.
  - **ADS-073** abstention evaluation (`reference_stack/abstention_eval.py`, `m7/abstention-*.json`, `make analytics-m7-abstention`): 30 chosen-model-output cases through the whole pipeline; seven proposed gates met (zero guesses, zero queries
    run on abstention, no confidence claims). **Fixed a defect:** an unsupported request was reported as a retryable `planner_unavailable` outage; it is now `refuse / unsupported_request`. **Open gap:** the scripted model answered all 4 near-miss
    questions (no intent-echo check exists); a real model or such a check is the user's decision. Packet: `ADS-073-abstention-evaluation.md`.
  - **ADS-074** isolation evaluation (`reference_stack/isolation_eval.py`, `m7/isolation-thresholds.proposed.json`, `make analytics-m7-isolation`): 24 hostile probes over REST and agent tools (other tenant, purposes, requester/automated/agent reviewing, bad tokens) + the
    ADS-067 corpus + ADS-070 protected cases; seven proposed gates met; each defence shown able to fail. Not an independent security review. Caveat: "automated" is recognised by id prefix/delegation claim only. Open findings F-02/F-03/F-05 listed. Packet: `ADS-074-isolation-evaluation.md`.
  - **Next:** PRs #25-#29 (ADS-055..059) are all merged to `main` (the last three on 2026-10-13). M5's packets are implemented
    and in `review`. **Wave 6A (M6) is implemented:** ADS-060, ADS-062, ADS-063 (all `review`); next is wave 6B (ADS-061 MCP adapter,
    ADS-064 customer-data-plane simulator, ADS-065 traces/metrics/redaction). Open user decisions: approve/amend the
    proposed thresholds for ADS-054..059 and the rollout policy and drift rules; the M5 gate `separation_of_duties_review`;
    independent review of ADS-040..060; M1 certification (pending); nothing was validated live.
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
  `test_ads045_analyze_api.py`); after ADS-046 **339 passed** (+9 in `test_ads046_shadow.py`); ADS-047 changed no Python test count (web: 18 tests); after ADS-048 **346 passed** (+7 in `test_ads048_reference_stack.py`); after ADS-049 **353 passed** (+6 golden, +1 ADS-045); focused `ruff check`/`format
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

- Independent review of ADS-040 to ADS-049 (manifest `review` → `complete`).
- M1 human semantic certification (still pending; nothing here certifies any
  ontology or contract).
- Live validation of PostgreSQL, OpenSearch, and catalog providers.
- Whether to open a PR from this branch and against which base (`main` lacks the
  ADS history).
- M4 `local_demo_review` is approved (2026-10-09). Later human gates: M5-M7 per the manifest.

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
