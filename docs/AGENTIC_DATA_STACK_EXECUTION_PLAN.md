# Agentic Data Stack Execution Plan

Status: Proposed execution baseline
Audience: Product, engineering, data platform, security, and delegated Luna agents
Scope: The governed analytics product under `apps/analytics-web`,
`services/analytics-api`, and `packages/platform_contracts`
Program IDs: `ADS-001` through `ADS-079`

Animated architecture:
[high-level system](diagrams/agentic-data-stack-system.html) and
[request graph with improvement loop](diagrams/agentic-data-stack-request.html).
Both are generated from the versioned
[Archify sources](diagrams/README.md).

## 1. Executive Decision

Evolve Compass Analytics into a governed data-stack agent by connecting the
semantic, compiler, metadata, policy, execution, evidence, and evaluation
components that already exist into one typed, durable agent graph.

The product is not a general autonomous data engineer. The first release is a
governed analytics decision agent that can answer questions using certified
business meaning, operate within customer policy, and produce replayable
evidence. It may propose semantic-model, metadata, and dbt changes, but it must
not apply customer data or pipeline changes without an explicit approval and a
separate execution policy.

The first reference stack is:

- PostgreSQL as the first customer-shaped warehouse and durable workflow state.
- DuckDB as the embedded local, evaluation, and governed data-lake-file
  execution adapter for Parquet and CSV sources.
- dbt artifacts plus OpenMetadata as context sources.
- Compass semantic contracts as the internal runtime model.
- Apache Ossie compatibility at the interchange boundary.
- OpenSearch as the derived lexical/vector context-retrieval index.
- A narrow typed graph runner in `analytics-api`, with durable checkpoints and
  an outbox in PostgreSQL.
- Existing compiler, policy, read-only gateway, evidence, and evaluation
  modules as the deterministic trust boundary.

Do not introduce a graph database in the first release. Relationships are
materialized into immutable context snapshots and traversed in bounded memory.
Add a graph store only after traces prove that bounded closure is a bottleneck.

Do not make LangGraph, an LLM framework, or an MCP server the policy boundary.
The graph is a product-domain state machine. Temporal remains an option for
future multi-hour workflows, but is not required for the synchronous query and
human-review lifecycle described here.

## 2. Final Product Outcome

An authorized user or calling agent can submit a messy business question and
receive one of five explicit outcomes: answer, clarify, refuse, review, or
fail. A successful answer is derived from certified semantics, executed within
budget and policy, and accompanied by immutable evidence.

```text
Question
  -> identity and purpose
  -> context retrieval and ontology resolution
  -> typed analytical intent
  -> ambiguity and certification gate
  -> deterministic compile
  -> policy and cost gate
  -> optional human approval
  -> read-only execution
  -> result validation
  -> evidence-backed explanation
  -> audit, evaluation, and correction signals
```

The final release gate requires:

- No raw model-generated SQL enters the certified execution path.
- Every selected metric, dimension, relationship, filter, and policy resolves
  to an immutable version and source.
- Unauthorized, stale, ambiguous, unsupported, and over-budget requests fail
  closed.
- Every terminal graph path is bounded, replayable, and observable.
- Golden answers are evaluated by result equivalence and trace evidence, not
  prose similarity alone.
- Human corrections cannot change production behavior until reviewed,
  evaluated, versioned, and promoted.
- The same product code onboards a second tenant without domain-specific code.

## 3. Decisions Requiring Confirmation

The plan proceeds with the recommended defaults below. A different answer does
not block Milestones 0-2, but must be resolved before Milestone 3 closes.

| Decision | Recommended default | Decision deadline |
|---|---|---|
| First execution adapters | PostgreSQL for customer-shaped execution; DuckDB for local and data-lake files | Before ADS-040 |
| First transformation source | dbt manifest/catalog/run-results | Before ADS-013 |
| First catalog | OpenMetadata; direct inspection remains supported | Before ADS-012 |
| Semantic authority | Compass runtime contract with Apache Ossie import/export | Before ADS-011 |
| Initial action scope | Read-only analytics plus reviewable change proposals | Before ADS-050 |
| Runtime location | Local and staging first; customer-VPC contract preserved | Before ADS-064 |
| Model policy | Provider-neutral; pinned model per release, deterministic fallback | Before ADS-032 |

## 4. Product and System Boundaries

### Compass owns

- The normalized ontology and immutable context snapshot.
- Certified semantic-contract lifecycle and runtime compatibility.
- Typed analytical intent and deterministic SQL compilation.
- Agent graph state, transition rules, budgets, and checkpoints.
- Authorization decisions that augment source-system enforcement.
- Evidence, review history, corrections, evaluations, and releases.

### Customer systems own

- Physical data and warehouse-native access controls.
- Technical metadata, lineage, quality, and freshness at their source.
- dbt models, tests, and documentation.
- Identity, groups, and user lifecycle.
- Approval authority for production semantic or pipeline changes.

### Explicit non-goals for the first release

- Replacing a warehouse, catalog, transformation engine, or BI product.
- Unbounded autonomous schema or pipeline modification.
- Generic browser or shell automation inside the data plane.
- Training a foundation model.
- Copying customer row-level data into the control plane.
- Treating model confidence or an LLM judge as an authorization signal.

### DuckDB boundary

DuckDB is a first-class execution adapter, not a replacement for the customer
warehouse. It provides fast, reproducible local evaluation and governed
read-only querying over approved Parquet and CSV locations. The adapter must:

- Compile from the same typed analytical intent and certified semantics as
  every other dialect.
- Restrict file access to tenant-scoped allowlisted roots and reject arbitrary
  paths, URLs, extensions, `ATTACH`, installation, and secret-management SQL.
- Disable or explicitly allowlist external access and extension loading.
- Apply the same row, byte, time, memory, concurrency, and evidence budgets.
- Pass result-equivalence tests against PostgreSQL for the portable semantic
  subset and report intentional dialect differences.
- Never use a DuckDB result as proof that PostgreSQL or another customer
  warehouse enforces equivalent permissions or runtime behavior.

## 5. Target Architecture

```text
Client / MCP caller / analytics web
                 |
                 v
        API and identity boundary
                 |
                 v
  +--------------------------------------------+
  | Typed agent graph                          |
  |                                            |
  | bootstrap -> retrieve -> resolve -> plan   |
  |       |          |          |       |      |
  |       +---- context snapshot -------+      |
  |                                            |
  | clarify/refuse <- validate -> compile      |
  |                                  |         |
  |                     policy -> estimate     |
  |                                  |         |
  |                       approve -> execute   |
  |                                  |         |
  |                  validate -> explain       |
  +--------------------------------------------+
                 |
        +--------+---------+
        |                  |
        v                  v
 durable run state     evidence and evals
 in PostgreSQL         in append-only store
        |
        v
 outbox / resume worker

Context sources                 Derived retrieval plane
dbt / OpenMetadata / DB -----> immutable snapshot -----> OpenSearch
                                        |
                                        v
                            certified semantic registry

Customer execution boundary
compiled plan -> source policy -> read-only gateway
                                      |-> PostgreSQL/customer warehouse
                                      +-> DuckDB/allowlisted lake files
```

### Storage choices

| Data | Authority | Derived/indexed copy |
|---|---|---|
| Physical schema, lineage, quality | Customer database/catalog | Context snapshot and OpenSearch |
| Semantic definitions | Git-backed Compass registry | Context snapshot and OpenSearch |
| Identity and groups | Customer IdP | Request-scoped claims only |
| Agent run state | Analytics PostgreSQL | Metrics/traces |
| Review and correction state | Analytics PostgreSQL | Searchable audit projection |
| Query evidence | Append-only evidence store | Operational index without sensitive rows |
| Customer result rows | Customer data plane | Not retained unless tenant policy permits |
| Local/lake analytical files | Tenant-approved file/object source | DuckDB ephemeral read-only views |

## 6. Ontology and Context Layer

The ontology is a versioned graph of business meaning. It is not a free-form
knowledge graph and it is not inferred at execution time.

### Ontology layers

| Layer | Core objects | Primary sources |
|---|---|---|
| L0 physical | DataSource, Dataset, Field, Key, Constraint | Database, catalog |
| L1 transformation | Model, Test, Exposure, LineageEdge | dbt, catalog |
| L2 business semantics | Entity, Grain, Metric, Dimension, Relationship, Filter | Certified semantic registry |
| L3 organization | BusinessConcept, GlossaryTerm, Synonym, Owner, Domain | Catalog, approved overrides |
| L4 trust and policy | Classification, Policy, Purpose, Certification, QualitySignal | Catalog, IdP, Compass policy |
| L5 operations | Freshness, CostProfile, QueryCapability, RuntimeHealth | Warehouse, telemetry |
| L6 learning | QuestionTemplate, Correction, EvaluationCase, Approval | Compass evidence and review |

Every node and edge carries `tenant_id`, stable ID, source, source version,
observed time, effective time, certification state, and content fingerprint.
No context object without provenance may enter a certified run.

### Source precedence

1. Warehouse policy and permissions always win for data access.
2. Certified Compass semantic definitions govern analytical meaning.
3. Customer-approved catalog glossary, owners, and classifications govern
   organizational context.
4. dbt governs transformation lineage, tests, and model documentation when it
   is newer and attributable.
5. Direct inspection fills physical metadata gaps but cannot create certified
   business meaning.
6. Model-inferred synonyms or relationships remain proposals until approved.

Conflicts produce a quality finding. They do not silently resolve by recency.

### Apache Ossie compatibility

Compass keeps a richer internal runtime contract because lifecycle, policy,
quality, and evidence requirements exceed a semantic interchange format. The
boundary must support:

- Import of supported Ossie datasets, fields, metrics, dimensions,
  relationships, expressions, AI context, and extensions.
- Export of the portable subset without losing stable identity.
- A compatibility report for unsupported or lossy fields.
- Round-trip tests for the supported subset.
- Explicit version pinning because the standard is still evolving.

### Context pack

Each agent step receives the minimum immutable context pack needed for that
step. The pack contains IDs and excerpts, never an unbounded catalog dump.

```text
ContextPack
  identity: tenant, user, groups, purpose
  request: normalized question, locale, conversation reference
  candidates: ranked datasets, concepts, metrics, dimensions
  graph_closure: bounded approved relationships and policies
  quality: freshness, certification, conflicts, missing fields
  examples: approved question/intent pairs only
  budget: token, retrieval, graph-depth, latency limits
  provenance: source and version for every included object
```

Context retrieval is evaluated on both recall and efficiency: top-k recall,
certified-object precision, graph-closure completeness, stale-context rate,
tokens per successful intent, and cost per reasoning step.

## 7. Agent Graph and Loop Engineering

### Graph state

`AgentRunState` is a strict versioned contract. It includes request and tenant
identity, current node, transition count, context snapshot ID, typed intent,
policy and cost decisions, approval state, compiled plan reference, execution
reference, evidence reference, errors, and terminal outcome. Nodes may only
write fields declared in their output contract.

### Node classes

| Class | Examples | Implementation rule |
|---|---|---|
| Deterministic | identity, validation, compile, policy, cost, execute | No LLM; pure or dependency-injected code |
| Model-assisted | intent extraction, synonym proposal, clarification wording, explanation | Structured output, pinned prompt/model, bounded context |
| Human | approval, semantic certification, correction promotion | Durable pause with identity and expiry |
| External | metadata fetch, warehouse estimate, query execution | Timeout, idempotency key, typed failure |

### Allowed request-time loops

| Loop | Maximum | May change | Terminal behavior |
|---|---:|---|---|
| Clarification | 2 user turns | Missing intent fields | Refuse or review after limit |
| Context expansion | 1 expansion | Candidate set and bounded closure | Clarify if still insufficient |
| Intent repair | 1 model retry | Invalid structured intent only | Review; never emit raw SQL |
| Compile repair | 1 deterministic rewrite | Dialect-safe canonicalization | Fail or review |
| Transient execution retry | 1 | Connection attempt only | Fail with preserved evidence |
| Explanation repair | 1 | Prose grounded in fixed result | Return evidence without prose |

There is no open-ended reason-act loop. Each transition consumes a run budget,
and repeated state fingerprints terminate the run as a cycle.

### Offline improvement loop

```text
production trace or human correction
  -> classify root cause
  -> propose context / semantic / prompt / code change
  -> create immutable candidate version
  -> run offline and adversarial evaluations
  -> independent human review
  -> shadow comparison
  -> canary promotion
  -> monitor and automatically roll back on gate failure
```

The agent may generate a proposal or pull-request payload. It cannot certify
its own proposal, alter the golden expected result, lower a release threshold,
or promote itself.

## 8. Harness Engineering

The harness is a product subsystem, not a collection of mock-heavy tests.

### Four harnesses

| Harness | Purpose | Required capability |
|---|---|---|
| Component harness | Verify every node and adapter | Contract suite, fakes, deterministic IDs/time |
| Graph harness | Verify transitions and termination | Scenario DSL, checkpoints, trace assertions |
| Data harness | Verify analytical correctness | Pinned fixtures, result equivalence, fanout traps |
| Operations harness | Verify real boundaries | Containers, fault injection, load, backup/replay |

### Scenario format

Each versioned scenario declares:

- Tenant, identity, purpose, question, and prior turns.
- Pinned ontology, semantic contract, metadata snapshot, policy, model, prompt,
  and warehouse fixture versions.
- Fake or live tool responses and injected failures.
- Expected terminal outcome and allowed graph transitions.
- Expected selected objects, intent, SQL AST properties, policy decision,
  result fingerprint, evidence fields, latency, token, and cost budgets.

### Grading hierarchy

1. Security and policy invariants are absolute pass/fail gates.
2. Result equivalence is the correctness authority for answer cases.
3. Typed intent and selected semantic IDs isolate planning errors.
4. Trace topology detects skipped gates, excess loops, and hidden retries.
5. Evidence completeness verifies replayability.
6. Retrieval, latency, token, and cost metrics detect efficiency regressions.
7. LLM judges may assess explanation usefulness only; they cannot override the
   deterministic grades above.

## 9. Milestone Plan

Each packet below is sized for one Luna implementation session. A packet is
complete only when its acceptance evidence is committed. Documentation-only
completion is not accepted for implementation packets.

### Milestone 0: Program and graph foundations

Goal: Freeze product boundaries and introduce durable, typed graph contracts
without changing public query behavior.

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| ADS-001 | Architecture ADR and product/non-goal boundary | Existing EA baseline | ADR approved; legacy and target paths named |
| ADS-002 | Graph-runtime ADR: internal runner now, Temporal trigger later | ADS-001 | Alternatives, failure modes, and migration trigger recorded |
| ADS-003 | Versioned `AgentRunState`, node I/O, transition, and terminal outcome contracts | ADS-002 | Serialization, version, invalid-state, and transition tests |
| ADS-004 | Typed tool registry with capability, risk, timeout, and idempotency metadata | ADS-003 | Undeclared tools and incompatible versions fail closed |
| ADS-005 | PostgreSQL run checkpoint, lease, transition log, and outbox schema | ADS-003 | Migration plus crash/resume and duplicate-delivery tests |
| ADS-006 | Legacy, shadow, governed, and disabled routing flags | ADS-003 | Routing tests prove no accidental governed-path activation |
| ADS-007 | Baseline current V1 accuracy, latency, cost, and failure report | None | Reproducible report and immutable fixture/model versions |
| ADS-008 | Apache Ossie compatibility ADR and mapping table | ADS-001 | Supported, extended, and lossy fields explicitly listed |
| ADS-009 | Milestone-0 integration gate and threat-model update | ADS-003 to ADS-008 | CI green; security reviewer signs graph trust boundaries |

Exit gate: A run can be created, checkpointed, resumed, and terminated through
a fake two-node graph with a complete transition audit. Public V1 behavior is
unchanged.

### Milestone 1: Ontology and context layer

Goal: Produce one immutable, provenance-complete context snapshot from
PostgreSQL, dbt, OpenMetadata, and certified Compass semantics.

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| ADS-010 | Versioned ontology node/edge and provenance contracts | ADS-008 | Cross-reference, tenant, temporal, and provenance tests |
| ADS-011 | Apache Ossie import, export, and compatibility report | ADS-008, ADS-010 | Supported subset round-trips without semantic loss |
| ADS-012 | Rich OpenMetadata mapping for lineage, glossary, quality, freshness, classification | ADS-010 | Provider conformance suite with pinned API fixtures |
| ADS-013 | Rich dbt mapping for models, tests, lineage, exposures, metrics, freshness | ADS-010 | Manifest/catalog/run-results fixtures normalize correctly |
| ADS-014 | PostgreSQL and DuckDB physical metadata providers | ADS-010 | Least-privilege inspection and allowlisted-file tests |
| ADS-015 | Source merge, precedence, conflict, and tombstone engine | ADS-012 to ADS-014 | Deterministic merge and conflict tests |
| ADS-016 | Immutable context snapshot builder and content fingerprint | ADS-015 | Same inputs reproduce fingerprint; changed source invalidates it |
| ADS-017 | OpenSearch context index and tenant/certification filters | ADS-016 | Lexical/vector retrieval never crosses tenant or lifecycle scope |
| ADS-018 | Bounded context-pack builder with graph closure and token budget | ADS-017 | Golden packs meet recall and token limits |
| ADS-019 | Ontology/context quality harness and report | ADS-011 to ADS-018 | Freshness, conflict, provenance, recall, and round-trip gates pass |

Exit gate: Every context object used by a run can be traced to its source and
version. A stale, conflicting, uncertified, or cross-tenant object cannot enter
the certified context pack.

### Milestone 2: Deterministic agent harness

Goal: Make every graph path reproducible locally before connecting the live
planner or warehouse.

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| ADS-020 | Versioned scenario and expected-trace schema | ADS-003 | Invalid and incompatible fixtures fail with useful errors |
| ADS-021 | Fake IdP, catalog, semantic registry, model, policy, and warehouse providers | ADS-020 | Fakes pass the same provider contracts as real adapters |
| ADS-022 | Deterministic clock, ID, random, token, and cost controls | ADS-020 | Repeated run yields identical semantic report |
| ADS-023 | Graph harness with node, edge, terminal-state, and loop assertions | ADS-020 to ADS-022 | Missing/extra transitions and cycles fail independently |
| ADS-024 | Node contract kit for success, typed error, timeout, and cancellation | ADS-023 | Every registered node passes the conformance suite |
| ADS-025 | Fault-injection DSL for stale context, timeouts, denial, crash, and malformed model output | ADS-023 | Each fault reaches its expected bounded terminal state |
| ADS-026 | Trace capture, redaction, export, and deterministic replay | ADS-023 | A stored trace replays without live model/network access |
| ADS-027 | Layered graders for retrieval, intent, AST, result, policy, trace, and evidence | ADS-023 | Deliberate defects fail the correct grader |
| ADS-028 | JSON, JUnit, and concise Markdown report renderer | ADS-027 | CI artifacts identify case, stage, version, and regression |
| ADS-029 | CI matrix, baseline lock, and threshold-change approval rule | ADS-024 to ADS-028 | Pull requests cannot silently lower gates or replace expected results |

Exit gate: At least 30 scenarios cover every terminal outcome, all allowed
loops, malformed model output, denial, timeout, crash/resume, and replay. The
suite is network-free and deterministic.

### Milestone 3: Governed agent graph

Goal: Connect the existing components through the typed graph while all
external actions still use fakes.

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| ADS-030 | Graph runner with transition allowlist, budget, cancellation, and cycle detection | ADS-009, ADS-023 | Illegal edge, repeat fingerprint, and budget exhaustion terminate |
| ADS-031 | Identity, purpose, tenant, and request bootstrap node | ADS-030 | Missing or inconsistent identity refuses before retrieval |
| ADS-032 | Model-assisted structured intent extraction node | ADS-018, ADS-030 | Schema-constrained output; no SQL field or unbounded retry |
| ADS-033 | Context retrieval and one-step expansion node | ADS-018, ADS-030 | Selection cites snapshot objects and honors retrieval budget |
| ADS-034 | Ontology entity, metric, time, and filter resolution node | ADS-032, ADS-033 | Synonyms cannot override certified IDs or tenant scope |
| ADS-035 | Ambiguity detector and clarification/resume node | ADS-034 | Targeted clarification preserves run identity and stops after two turns |
| ADS-036 | Certified intent validation and exploratory-review branch | ADS-034 | Uncertified intent cannot reach automatic compilation |
| ADS-037 | Compiler, policy, AST, and warehouse-estimate nodes | ADS-036 | Every execution candidate passes all deterministic gates in order |
| ADS-038 | Durable human-review pause, expiry, edit, approve, and reject path | ADS-005, ADS-037 | Identity-bound resume and stale-approval tests pass |
| ADS-039 | Graph-level adversarial and termination evaluation | ADS-030 to ADS-038 | All scenarios terminate within declared transition/loop budgets |

Exit gate: The complete fake-backed graph returns answer, clarify, refuse,
review, and fail outcomes with exact expected traces. It is impossible to skip
identity, certification, policy, cost, or evidence gates.

### Milestone 4: Live read-only execution and evidence

Goal: Replace fakes one boundary at a time and expose the governed path as a
versioned, opt-in API without removing V1.

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| ADS-040 | PostgreSQL and DuckDB read-only gateway/compiler adapters | ADS-037 | Dialect, file isolation, timeout, cancellation, row, byte, and cost limits pass |
| ADS-041 | Result shape, grain, invariant, and fingerprint validation | ADS-040 | Fanout, missing groups, invalid totals, and truncation are detected |
| ADS-042 | Immutable evidence envelope and append-only persistence | ADS-041 | Every terminal outcome has required provenance and policy evidence |
| ADS-043 | Grounded explanation and visualization-spec node | ADS-041, ADS-042 | Claims cite fixed result/semantic IDs; repair cannot alter result |
| ADS-044 | Live dbt/OpenMetadata refresh and snapshot publication worker | ADS-016 | Incremental refresh, tombstone, failure, and stale-snapshot tests |
| ADS-045 | `POST /api/v2/analytics/analyze` and resume endpoints | ADS-038, ADS-043 | OpenAPI, auth, idempotency, status, and outcome contract tests |
| ADS-046 | V1 shadow adapter and privacy-safe comparison recorder | ADS-045 | V1 response unchanged; governed path cannot execute in shadow mode |
| ADS-047 | Evidence-first analytics web workflow | ADS-045 | Answer, clarify, review, refuse, trace, and replay states work |
| ADS-048 | Local reference stack and seeded PostgreSQL/DuckDB demos | ADS-040, ADS-044 to ADS-047 | One command starts dependencies and runs both smoke journeys |
| ADS-049 | Milestone-4 end-to-end golden report | ADS-040 to ADS-048 | Pinned local live-boundary suite meets correctness and trust gates |

Exit gate: A local user can ask a messy Olist question, clarify it if needed,
execute certified SQL against PostgreSQL, and inspect a replayable evidence
record. The live path never executes model-authored SQL.

### Milestone 5: Safe learning and correction loops

Goal: Learn from failures without allowing online self-modification.

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| ADS-050 | Structured feedback and correction capture | ADS-042, ADS-047 | Feedback links exact run, evidence, identity, and reason |
| ADS-051 | Root-cause taxonomy and deterministic triage rules | ADS-050 | Retrieval, ontology, intent, semantic, policy, execution, and prose separated |
| ADS-052 | Semantic/context change proposal generator | ADS-051 | Proposal is a versioned diff with provenance; never auto-certified |
| ADS-053 | dbt docs/test change proposal generator | ADS-051 | Output is constrained to approved files and includes validation command |
| ADS-054 | Prompt/example candidate registry | ADS-051 | Candidate cannot overwrite a released version |
| ADS-055 | Independent review and certification workflow | ADS-052 to ADS-054 | Author cannot approve own change; expiry and rejection audited |
| ADS-056 | Candidate evaluation and affected-case selection | ADS-055 | Changed ontology/context maps to targeted plus full regression suites |
| ADS-057 | Shadow, canary, promotion, and automatic rollback controller | ADS-056 | Bad candidate rolls back without losing evidence or run state |
| ADS-058 | Drift monitors for context, retrieval, intent, outcomes, latency, and cost | ADS-049, ADS-057 | Synthetic drift trips the expected alert and runbook |
| ADS-059 | Closed-loop safety and poisoning evaluation | ADS-050 to ADS-058 | Malicious feedback cannot change goldens, policy, or production behavior |

Exit gate: An incorrect answer can become a reviewed candidate fix, pass
targeted and full evaluations, run in shadow, promote through canary, and roll
back. No participant or model can bypass separation of duties.

### Milestone 6: Agent-operable and enterprise runtime

Goal: Make the governed graph usable by people and other agents, with
production-shaped identity, isolation, and operations.

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| ADS-060 | Versioned agent tool surface for analyze, status, clarify, approve, and evidence | ADS-045 | Tool schemas are strict, scoped, documented, and contract-tested |
| ADS-061 | MCP adapter over the same application service | ADS-060 | MCP cannot bypass API authorization, graph, or audit boundaries |
| ADS-062 | Portable machine-readable analysis artifact | ADS-042, ADS-060 | Artifact replays across web/API/MCP with stable IDs |
| ADS-063 | OIDC identity/group propagation and delegated-purpose policy | ADS-031, ADS-045 | Real IdP negative suite and group-change behavior pass |
| ADS-064 | Customer-data-plane protocol and local VPC-boundary simulator | ADS-040, ADS-063 | No result rows or credentials cross forbidden boundary |
| ADS-065 | End-to-end traces, metrics, logs, redaction, and correlation | ADS-042, ADS-064 | One run traces across API, graph, context, gateway, and evidence |
| ADS-066 | Per-tenant quotas, SLOs, cost attribution, and alerts | ADS-065 | Noisy-neighbor and denial-of-wallet load scenarios pass |
| ADS-067 | Threat model, prompt-injection, exfiltration, and inference suite | ADS-061 to ADS-066 | No unresolved critical/high findings in internal review |
| ADS-068 | Backup, restore, HA, rolling upgrade, and checkpoint compatibility | ADS-005, ADS-065 | Local/staging drills meet declared RPO/RTO |
| ADS-069 | Operations dashboard and runbooks for every release gate | ADS-058, ADS-065 to ADS-068 | Operator can diagnose and replay seeded failures |

Exit gate: Web, REST, and MCP callers receive equivalent governed outcomes.
Identity and tenant policy propagate end to end, and operational drills prove
that runs and evidence survive supported failures.

### Milestone 7: Final evaluation and pilot decision

Goal: Prove the complete system against realistic questions, adversarial
conditions, a second tenant, and a staging-shaped runtime.

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| ADS-070 | Versioned 100-case reference corpus and 25-50 customer-style P0 questions | ADS-049 | Owners approve definitions and expected results independently |
| ADS-071 | End-to-end correctness and PostgreSQL/DuckDB equivalence evaluation | ADS-070 | Thresholds below pass on pinned release candidate |
| ADS-072 | Context/ontology retrieval and token-efficiency evaluation | ADS-019, ADS-070 | Recall, provenance, freshness, and token thresholds pass |
| ADS-073 | Ambiguity, abstention, unsupported-question, and calibration evaluation | ADS-039, ADS-070 | Agent refuses or clarifies instead of guessing |
| ADS-074 | Security, tenant-isolation, and policy adversarial evaluation | ADS-067, ADS-070 | Zero policy or cross-tenant violations |
| ADS-075 | Reliability, crash/replay, dependency-failure, and chaos evaluation | ADS-068 | Declared availability and recovery gates pass |
| ADS-076 | Latency, concurrency, token, warehouse, and infrastructure cost evaluation | ADS-066 | P95 and unit-economics thresholds pass at target load |
| ADS-077 | Model/provider variance, degraded-mode, and rollback evaluation | ADS-057, ADS-070 | Provider failure is bounded; promoted behavior remains reproducible |
| ADS-078 | Second-tenant and Apache Ossie portability onboarding drill | ADS-011, ADS-064 | Onboards without product-code or contract-schema changes |
| ADS-079 | Final evidence manifest and human go/no-go review | ADS-071 to ADS-078 | Product, engineering, data owner, security, and operations sign off |

Exit gate: The release candidate passes all deterministic gates, has no open P0
defects, and contains a signed manifest linking code, containers, contracts,
context, models, prompts, policies, corpus, reports, and runbooks.

## 10. Final Evaluation Thresholds

Initial thresholds are deliberately demanding. ADS-007 establishes the
baseline; changing a threshold requires a reviewed rationale and cannot be
part of the same change that regresses it.

| Dimension | Pilot gate |
|---|---:|
| P0 question result equivalence | 100% |
| Full answer-case result equivalence | >= 95% |
| Certified dataset/metric top-3 recall | >= 98% |
| Unsupported or unsafe request refusal recall | 100% |
| Ambiguous request clarify-or-review recall | >= 95% |
| Policy and tenant-isolation violations | 0 |
| Executed queries authored as raw model SQL | 0 |
| Required evidence completeness | 100% |
| Replay fingerprint equivalence | 100% |
| PostgreSQL/DuckDB portable-subset result equivalence | 100% |
| Runs exceeding loop/transition budget | 0 |
| P95 warm answer latency, local reference data | <= 8 seconds |
| P95 deterministic compile/policy overhead | <= 250 ms |
| Context tokens per successful intent | Baseline -20% by final RC |
| Unreviewed correction promotions | 0 |
| Critical/high security defects | 0 open |

Latency and cost thresholds must be re-baselined for the selected staging
model and warehouse. Correctness and security thresholds may not be relaxed to
compensate for infrastructure limits.

## 11. Dependency and Dispatch Waves

| Wave | Packets | Parallelism | Merge gate |
|---|---|---|---|
| 0A | ADS-001, ADS-007, ADS-008 | Parallel | Architecture review |
| 0B | ADS-002, ADS-003, ADS-006 | ADS-003 follows ADS-002 | Contract suite |
| 0C | ADS-004, ADS-005, ADS-009 | ADS-004/005 parallel | Milestone 0 gate |
| 1A | ADS-010, ADS-012, ADS-013, ADS-014 | ADS-012/13/14 after 010 | Provider conformance |
| 1B | ADS-011, ADS-015 | Parallel after prerequisites | Mapping/merge tests |
| 1C | ADS-016, ADS-017, ADS-018, ADS-019 | Sequential critical path | Milestone 1 gate |
| 2A | ADS-020, ADS-021, ADS-022 | 021/022 follow 020 | Fixture determinism |
| 2B | ADS-023, ADS-024, ADS-025 | 024/025 follow 023 | Harness conformance |
| 2C | ADS-026, ADS-027, ADS-028, ADS-029 | 026/027 parallel | Milestone 2 gate |
| 3A | ADS-030, ADS-031, ADS-032, ADS-033 | 031/32/33 after 030 | Node contract gate |
| 3B | ADS-034, ADS-035, ADS-036 | 035/36 follow 034 | Outcome paths |
| 3C | ADS-037, ADS-038, ADS-039 | Sequential | Milestone 3 gate |
| 4A | ADS-040, ADS-044 | Parallel | Live adapter tests |
| 4B | ADS-041, ADS-042, ADS-043 | Sequential | Evidence gate |
| 4C | ADS-045, ADS-046, ADS-047 | 046/47 after 045 | API/UI compatibility |
| 4D | ADS-048, ADS-049 | Sequential | Milestone 4 gate |
| 5A | ADS-050, ADS-051 | Sequential | Correction taxonomy |
| 5B | ADS-052, ADS-053, ADS-054 | Parallel | Proposal isolation |
| 5C | ADS-055, ADS-056, ADS-057 | Sequential | Promotion gate |
| 5D | ADS-058, ADS-059 | Parallel | Milestone 5 gate |
| 6A | ADS-060, ADS-062, ADS-063 | Parallel | Agent/identity contracts |
| 6B | ADS-061, ADS-064, ADS-065 | Parallel after dependencies | Boundary tests |
| 6C | ADS-066, ADS-067, ADS-068, ADS-069 | 067/68 parallel | Milestone 6 gate |
| 7A | ADS-070 | Single owner | Corpus approval |
| 7B | ADS-071 to ADS-078 | Parallel by evaluation dimension | All reports pass |
| 7C | ADS-079 | Human review | Final go/no-go |

## 12. Luna Execution Protocol

Luna may execute implementation, tests, reports, and documentation for every
packet. Architecture, security, semantic certification, threshold changes, and
the final go/no-go require independent human review; a delegated model does not
self-approve those gates.

The machine-readable source for task status and dependency selection is
[`agentic-data-stack-program.yaml`](execution/enterprise-analytics/agentic-data-stack-program.yaml).
The plan defines intent and acceptance; the manifest records execution state.
They must be changed together when tasks or dependencies change.

### Controller loop

At the start of each execution session, the dispatcher must:

1. Read the manifest and verify that every dependency marked `complete` has a
   reachable commit and acceptance evidence.
2. Select only `planned` or `ready` tasks whose dependencies are complete.
3. Mark selected tasks `in_progress` before dispatch and assign non-overlapping
   worktrees for parallel tasks.
4. Require the packet result, commit, validation output, and residual risks;
   move the task to `review`, not directly to `complete`.
5. After independent review and integration, record the merge commit and mark
   the task complete.
6. When every task in a milestone is complete, run its full exit gate, publish
   the milestone report, obtain the named human gate, then update and push the
   manifest.
7. Continue with the next unblocked wave until ADS-079 pauses for final human
   go/no-go. A failed gate returns the owning task to `in_progress` with the
   failure evidence; it never skips forward.

### Packet contract

Before implementation, create or expand a packet under
`docs/execution/enterprise-analytics/` containing:

1. Objective and user-visible outcome.
2. Dependencies and evidence that they are merged.
3. Allowed files and explicitly forbidden scope.
4. Required behavior and invariants.
5. Acceptance tests and exact validation commands.
6. Observability, security, migration, and rollback requirements where relevant.
7. Deliverables and stop conditions.

### Execution rules

1. One packet, one worktree, one branch, one primary owner.
2. Read the target code and dependency contracts before editing.
3. Add failing tests or fixtures before production behavior when practical.
4. Do not change public contracts, thresholds, dependencies, migrations, or
   cross-product packages unless the packet explicitly owns them.
5. Do not use network services in deterministic component/graph tests.
6. Preserve unrelated user changes and stop on overlapping ownership.
7. Run focused tests, the analytics integration gate, and `git diff --check`.
8. Commit the packet with its evidence; do not mark complete from prose alone.
9. After each milestone, merge in dependency order, run the entire milestone
   gate, publish the report, and push the integrated commit.
10. If acceptance cannot be proved, record the blocker and leave the packet
    incomplete. Never weaken the acceptance criteria to make it pass.

### Standard Luna dispatch prompt

```text
Execute packet <ADS-ID> from the Agentic Data Stack Execution Plan.

Work only in the packet's allowed scope. Inspect merged dependencies first.
Implement production behavior and focused tests, then run every validation
command in the packet plus the analytics integration gate. Do not lower eval
thresholds, replace expected results, bypass policy, or expand scope. Record
acceptance evidence in the packet, commit the complete change, and report the
commit, files changed, tests run, and any residual risk. If a stop condition is
met, do not improvise around it; document the blocker precisely.
```

### Review protocol

- A separate reviewer checks behavior, security invariants, test quality,
  backward impact, and packet scope.
- The author fixes findings in the same packet branch.
- The integration owner merges only after dependencies and required reviews
  are satisfied.
- Milestone reports record commit SHAs, artifact fingerprints, commands,
  results, exceptions, and named sign-offs.

## 13. Standard Validation Gates

From the repository root unless a packet narrows the command:

```bash
ruff check packages/platform_contracts services/analytics-api/app services/analytics-api/tests
(cd services/analytics-api && PYTHONPATH=.:../.. pytest -q)
git diff --check
```

Each milestone adds its own deterministic evaluation command. ADS-029 must
provide one stable entry point, expected to become:

```bash
make test-analytics-agent
make eval-analytics-agent
```

Do not claim a milestone complete while those commands depend on an
undocumented current working directory or an unpinned external service.

## 14. Program Completion Definition

The program is complete only when ADS-079 links all of the following for one
release candidate:

- Source commit and signed container digests.
- Database migration and rollback evidence.
- Semantic, ontology, context, policy, prompt, and model versions.
- Complete deterministic, adversarial, load, recovery, and portability reports.
- A replayable trace for every terminal outcome.
- A successful second-tenant onboarding report.
- PostgreSQL and DuckDB adapter-conformance and portable-result-equivalence reports.
- Security, operations, product, and customer-data-owner sign-offs.

Azure production deployment is outside this plan. Local and Azure staging may
be used to prove runtime and operational gates, but no milestone requires or
authorizes production deployment.

## 15. External Design Inputs

This plan aligns with the community move toward portable semantics,
agent-readable context, grounded evaluation, and policy-aware tool execution:

- Ian Macomber, [The Shape and Feel of the Post-AI Data Stack](https://www.iandmacomber.com/blog/post-ai-data-stack/)
- Apache Software Foundation, [Apache Ossie](https://ossie.apache.org/)
- OpenMetadata, [AI SDK](https://docs.open-metadata.org/latest/api-reference/sdk/ai-sdk)
- Snowflake, [Cortex Analyst evaluations](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst-evaluations)
- Databricks, [Genie Agents](https://docs.databricks.com/aws/en/genie-agents/)
- IBM Research, [Recall Is Not Enough: Token-Centric Metrics for Agentic Schema](https://research.ibm.com/publications/recall-is-not-enough-token-centric-metrics-for-agentic-schema)
- arXiv, [Text-to-SQL for Enterprise Data Analytics](https://arxiv.org/abs/2507.14372)
- arXiv, [A Semantic-Layer-Mediated Agent for Natural Language to SQL over Heterogeneous Enterprise Databases](https://arxiv.org/abs/2606.31041)
- DuckDB Foundation, [DuckDB documentation](https://duckdb.org/docs/stable/)

Vendor benchmarks inform hypotheses, not acceptance thresholds. Compass gates
must be reproduced on pinned local fixtures and customer-approved questions.
