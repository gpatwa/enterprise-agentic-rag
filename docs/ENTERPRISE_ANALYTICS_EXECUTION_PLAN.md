# Enterprise Analytics Roadmap and Execution Plan

Status: Proposed execution baseline
Audience: Product, engineering, security, data platform, and delegated coding agents
Scope: The standalone analytics product under `apps/analytics-web`,
`services/analytics-api`, and `packages/platform_contracts`

> The continuation that integrates these components into a typed agent graph,
> ontology/context layer, safe improvement loop, and final end-to-end evaluation
> is maintained in the
> [Agentic Data Stack Execution Plan](AGENTIC_DATA_STACK_EXECUTION_PLAN.md).

## 1. Executive Decision

Build Compass Analytics as a catalog-neutral Trust and Execution layer for
enterprise analytics agents. Integrate with the customer's existing catalog and
identity systems; do not require OpenMetadata, DataHub, or another catalog as a
new system of record.

OpenMetadata is the first full catalog adapter and the recommended greenfield
catalog. Direct database and dbt ingestion support smaller or less mature
customers. DataHub and enterprise catalog adapters follow based on design
partner demand.

Compass owns the portable semantic contract, query intent, policy-aware
execution, evidence, and evaluation loop. A catalog supplies context; it does
not become the SQL security boundary.

## 2. Product Outcome

An authorized enterprise user can ask a business question and receive a
reproducible answer built from certified metrics, approved join paths, current
metadata, and enforced access policy. Every answer includes enough evidence to
replay, inspect, approve, or challenge the work.

The first enterprise release is successful when it can:

- Connect to one customer's warehouse, identity provider, and metadata source.
- Resolve questions against certified datasets and metrics without inventing
  joins or metric formulas.
- Clarify or refuse when business intent, access, or metadata is insufficient.
- Enforce tenant, role, row, and column policy before query execution.
- Execute through a read-only customer data plane with bounded cost and time.
- Record the request, context versions, plan, policy decision, SQL, result
  fingerprint, model version, and reviewer actions in an immutable audit trail.
- Detect regressions through customer-specific offline evaluations and
  production traces.

## 3. Current Baseline

### Available now

- Independent Analytics API and React web application.
- Versioned v1 request, result, schema, and health contracts.
- Static Olist table, relationship, and metric context.
- LLM-generated PostgreSQL with a read-only connection, timeout, row cap,
  allowlists, and basic cost checks.
- Local deterministic demo mode and an isolated analytics test suite and CI job.

### Gaps that block an enterprise pilot

- The metric definitions contain known grain problems. Average order value
  averages payment rows rather than per-order totals, and category revenue can
  multiply order-level payments across item-level joins.
- The model emits SQL directly; there is no typed analytical intent or governed
  semantic compilation step.
- SQL safety is primarily textual and is not a complete AST, authorization, or
  warehouse-cost policy.
- Metadata is static and Olist-specific. There is no provider interface,
  freshness signal, certification, ownership, or metadata quality gate.
- The public contract cannot represent clarification, refusal, provenance,
  policy decisions, confidence, review state, or audit evidence.
- Authentication is an optional local API key. Enterprise SSO, SCIM, delegated
  authorization, and customer-VPC execution are not wired to Analytics.
- There is no analytics golden dataset, result-equivalence evaluator, prompt or
  model registry, production trace store, or release quality gate.
- There are no analytics-owned migrations, tenant registry, durable semantic
  registry, or immutable audit store.

The existing demo is a useful vertical slice. It is not the base on which to
claim arbitrary enterprise text-to-SQL correctness.

## 4. Target Architecture

```text
Enterprise user or agent
          |
          v
Control plane: SSO, tenant routing, quotas, policy context
          |
          v
Customer data plane
  +-----------------------------------------------------------+
  | Intent planner                                            |
  |   -> metadata providers (catalog, dbt, direct inspection) |
  |   -> semantic registry and quality gate                   |
  |   -> clarify / refuse / certified analytical intent       |
  |                                                           |
  | Governed compiler                                         |
  |   -> approved metrics, dimensions, joins, filters         |
  |   -> identity-aware policy injection                      |
  |   -> SQL AST and warehouse cost validation                |
  |                                                           |
  | Read-only executor                                        |
  |   -> timeout, row/byte/cost budgets, cancellation         |
  |   -> result validation and fingerprint                    |
  +-----------------------------------------------------------+
          |
          +--> answer, visualization, citations, assumptions
          +--> immutable evidence and evaluation events
```

### System-of-record boundaries

| Concern | Authoritative source |
|---|---|
| Warehouse schema and technical lineage | Customer source/catalog |
| Owners, glossary, certification, quality | Customer catalog |
| Metrics, grain, approved joins, required filters | Compass semantic contract, synchronized with customer models |
| Authentication and group membership | Customer identity provider |
| Raw data access | Warehouse and customer data-plane credentials |
| Agent authorization decision | Compass policy engine plus source policy context |
| Query evidence and review history | Compass immutable audit store |
| Prompts, model versions, eval results | Compass AI operations registry |

### Architectural constraints

1. Catalog neutral: all catalog access is behind versioned provider protocols.
2. Contract first: models emit a typed analytical intent for the certified
   path, not arbitrary SQL.
3. Policy before execution: tenant, role, row, column, and purpose restrictions
   are applied before SQL reaches the warehouse.
4. Fail closed: missing semantics, stale context, unsupported operations, or
   indeterminate policy produce clarification, refusal, or review states.
5. Customer data stays in the data plane. The control plane receives metadata,
   telemetry, and result summaries only according to tenant policy.
6. No catalog fork: integrate through supported APIs and upstream extensions.
7. Independent deployability remains mandatory. Analytics cannot import
   support product internals.

## 5. Delivery Strategy

The roadmap is gate-driven rather than date-driven. Estimates assume three
engineers using delegated models for bounded implementation and test work. They
exclude customer procurement and an external SOC 2 audit.

| Stage | Indicative elapsed time | Exit gate |
|---|---:|---|
| 0. Correctness baseline | 2-3 weeks | Demo metrics and joins are provably correct |
| 1. Trusted semantic kernel | 4-6 weeks | Certified questions compile without free-form SQL |
| 2. Enterprise context integration | 4-6 weeks | One real catalog and warehouse work end to end |
| 3. Trust and execution layer | 4-6 weeks | Policy, evidence, approvals, and evals are operational |
| 4. Enterprise pilot readiness | 6-8 weeks | SSO, private data plane, reliability, and security gates pass |
| 5. General availability | Design-partner driven | Repeatable onboarding, support, compliance, and SLO evidence |

Stages overlap where the dependency map permits it. A credible design-partner
pilot is approximately 16-22 elapsed weeks; general availability is more likely
24-32 weeks. Model delegation can improve throughput, but it does not compress
customer feedback, security review, load testing, or operational proving time.

## 6. Execution Workstreams

### A. Correctness and public contracts

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| EA-001 | Freeze deterministic Olist fixtures and canonical expected results | None | Fixture checksum and SQL-independent expected values committed |
| EA-002 | Correct metric grain, payment/item fanout, category attribution, and delivery semantics | EA-001 | Golden tests cover single/multi-item and split-payment orders |
| EA-003 | Replace text-oriented SQL inspection with dialect-aware AST parsing | EA-001 | Adversarial CTE, subquery, function, comment, and multi-statement tests pass |
| EA-004 | Define v2 outcome model: answer, clarify, refuse, review, fail | EA-001 | Contract tests and backward compatibility policy approved |
| EA-005 | Add evidence, assumptions, confidence, provenance, policy, and review fields | EA-004 | OpenAPI examples and serialization tests pass |
| EA-006 | Create analytics-owned persistence and Alembic baseline | EA-004 | Empty database can migrate up/down in CI |

### B. Semantic contracts and compilation

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| EA-010 | Versioned semantic contract schema for datasets, entities, metrics, dimensions, grains, joins, filters, policies, and owners | EA-002, EA-004 | JSON Schema/Pydantic validation and invalid-contract tests |
| EA-011 | Git-backed local semantic registry with lifecycle states | EA-010 | Draft, certified, deprecated, and invalid states tested |
| EA-012 | Typed analytical intent IR independent of SQL dialect | EA-010 | Intent represents metric, grouping, time range, filters, sort, and limit |
| EA-013 | Deterministic compiler spike comparing Cube Core with a narrow internal compiler | EA-010, EA-012 | ADR records accuracy, policy, operability, licensing, and latency results |
| EA-014 | Implement selected compiler adapter and PostgreSQL dialect | EA-013 | Certified golden intents produce deterministic, executable SQL |
| EA-015 | Add join cardinality and aggregation-grain validation | EA-014 | Compiler rejects fanout and ambiguous many-to-many paths |
| EA-016 | Add mandatory filter and policy injection | EA-014 | Generated SQL cannot omit tenant and required business filters |
| EA-017 | Add dialect/provider extension points | EA-014 | Contract test proves a second dialect can be registered without planner changes |

### C. Metadata and context providers

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| EA-020 | Define `MetadataProvider`, `SemanticModelProvider`, and `PolicyProvider` protocols | EA-010 | Provider contract tests use fakes with no vendor imports |
| EA-021 | Direct PostgreSQL inspection provider | EA-020 | Tables, columns, keys, comments, and sample statistics normalize correctly |
| EA-022 | dbt manifest/catalog/run-results provider | EA-020 | dbt models, tests, lineage, descriptions, and exposures normalize correctly |
| EA-023 | OpenMetadata read-only adapter | EA-020 | Schemas, lineage, owners, glossary, tags, quality, and certification map correctly |
| EA-024 | Metadata quality and actionability score | EA-021 or EA-023 | Incomplete, stale, uncertified, and conflicting metadata fail defined gates |
| EA-025 | Semantic-first retrieval and ranked dataset selection | EA-024 | Top-3 dataset recall meets the evaluation threshold |
| EA-026 | Review-only exploratory fallback | EA-025 | Uncertified discoveries cannot reach automatic execution |
| EA-027 | DataHub adapter | EA-020, design-partner demand | Same conformance suite passes as OpenMetadata |
| EA-028 | Additional enterprise catalog adapters | EA-020, customer demand | Added through protocol without domain-model changes |

### D. Planner, clarification, and user experience

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| EA-030 | Planner emits typed intent and cited context IDs | EA-012, EA-025 | No certified request passes raw model SQL to execution |
| EA-031 | Ambiguity detector for metric, grain, time, dataset, and filter conflicts | EA-030 | Ambiguous eval cases ask targeted questions rather than guessing |
| EA-032 | Clarification continuation protocol | EA-004, EA-031 | A clarified request preserves identity, evidence, and audit linkage |
| EA-033 | Refusal and review policy engine | EA-024, EA-031 | Unsupported, stale, unauthorized, and high-risk cases are deterministic |
| EA-034 | Evidence-first result workspace | EA-005, EA-014 | UI shows metric definition, source, filters, SQL, assumptions, and freshness |
| EA-035 | Human approval queue for exploratory or high-risk queries | EA-033 | Approve, edit, reject, expire, and replay actions are audited |
| EA-036 | Saved certified analyses and parameterized replay | EA-034 | Replays bind new parameters without changing certified logic |

### E. Security, policy, and enterprise identity

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| EA-040 | Analytics tenant and user identity context | EA-004 | No production defaults for tenant/user; cross-tenant tests fail closed |
| EA-041 | OIDC/JWT integration with issuer, audience, key rotation, and groups | EA-040 | IdP integration and negative-token suite pass |
| EA-042 | SAML and SCIM integration strategy | EA-041 | ADR selects broker/direct approach; lifecycle test plan approved |
| EA-043 | RBAC/ABAC policy model with purpose and data classification | EA-040, EA-020 | Policy decision is deterministic and included in evidence |
| EA-044 | Row, column, masking, and tenant enforcement in compiler/executor | EA-016, EA-043 | Bypass and inference-oriented security tests pass |
| EA-045 | Customer-managed secrets and credential rotation | EA-040 | No warehouse secret enters logs or control-plane persistence |
| EA-046 | Audit event signing, append-only storage, export, and retention | EA-005, EA-006 | Tamper and completeness tests cover every query outcome |
| EA-047 | Threat model and abuse-case suite | EA-044, EA-046 | Security review covers prompt injection, SQL abuse, exfiltration, and denial of wallet |

### F. Data plane, reliability, and enterprise operations

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| EA-050 | Analytics-specific control-plane/data-plane protocol | EA-040 | Versioned registration, health, routing, cancellation, and usage contracts |
| EA-051 | Customer-VPC read-only execution gateway | EA-045, EA-050 | Data remains in VPC and all egress is policy controlled |
| EA-052 | Private connectivity patterns | EA-051 | PrivateLink/Private Endpoint/VPN reference deployment documented and tested |
| EA-053 | Query budgets, cancellation, concurrency, and warehouse quotas | EA-014, EA-051 | Load tests prove per-tenant isolation and bounded resource use |
| EA-054 | OpenTelemetry traces, metrics, structured logs, and correlation IDs | EA-004 | One query is traceable from ingress through evidence persistence |
| EA-055 | SLOs and alerting | EA-053, EA-054 | Availability, latency, error, eval, and cost alerts have runbooks |
| EA-056 | Backup, restore, DR, and evidence retention | EA-046 | Restore drill meets documented RPO/RTO |
| EA-057 | HA deployment, rolling upgrade, and migration safety | EA-050, EA-056 | Failure and rollback drills pass without cross-tenant impact |
| EA-058 | Usage metering, quotas, and cost attribution | EA-050, EA-054 | Usage reconciles by tenant, model, query, and warehouse |

### G. AI operations, evaluation, and release governance

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| EA-060 | Analytics evaluation harness with dataset selection, intent, SQL AST, and result equivalence graders | EA-001; intent grader follows EA-012 | Reproducible local and CI reports with pinned fixtures |
| EA-061 | Customer-specific golden dataset format and onboarding process | EA-060 | New tenant suite can be added without evaluator code changes |
| EA-062 | Ambiguity, refusal, security, and cost adversarial suites | EA-031, EA-044, EA-053 | Expected outcomes are asserted, not scored only by an LLM judge |
| EA-063 | Prompt, model, semantic-contract, and policy version registry | EA-010, EA-043 | Every evidence record resolves immutable versions |
| EA-064 | Offline release gates and baseline comparison | EA-060, EA-063 | CI blocks statistically or materially significant regressions |
| EA-065 | Shadow, canary, rollback, and model-provider failover | EA-054, EA-064 | A bad model/config can be detected and rolled back without data loss |
| EA-066 | Production quality and drift monitoring | EA-061, EA-065 | Alerts cover retrieval drift, clarification rate, execution errors, and semantic freshness |
| EA-067 | Human correction and validated query memory | EA-035, EA-063 | Corrections require provenance, scope, approval, expiry, and regression tests |

### H. Pilot, compliance, and customer operations

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| EA-070 | Design-partner discovery and authoritative question set | None | Named owners approve 25-50 high-value questions and source definitions |
| EA-071 | Repeatable connector and semantic onboarding workflow | EA-021 to EA-025 | A second tenant onboards without product code changes |
| EA-072 | Security whitepaper, data-flow inventory, and subprocessors | EA-047, EA-051 | Procurement packet reviewed by security counsel |
| EA-073 | SBOM, dependency scanning, image signing, and vulnerability SLA | EA-057 | Release artifacts are signed and policy checked |
| EA-074 | Penetration test and remediation | EA-047, EA-057 | No unresolved critical/high findings at pilot launch |
| EA-075 | Incident response, support escalation, and customer status process | EA-055 | Tabletop exercise and customer communication drill complete |
| EA-076 | DPA, retention/deletion, residency, and compliance roadmap | EA-046, EA-056 | Contractual controls map to implemented evidence |
| EA-077 | Pilot scorecard and go/no-go review | All pilot P0 items | Product, engineering, security, and customer sign off |

## 7. Phase Gates

### Gate 0: Correct demo kernel

- Canonical fixture results are independent of generated SQL.
- Metric-grain and fanout defects are fixed.
- AST validator rejects known unsafe and unsupported constructs.
- No current analytics test or CI regression.

### Gate 1: Trusted semantic kernel

- One certified domain is fully modeled as semantic contracts.
- Certified questions produce typed intents and deterministic compiled SQL.
- Fanout, ambiguous joins, missing mandatory filters, and stale contracts fail
  before execution.
- At least 95% result accuracy on the certified golden set and 100% on P0
  executive metrics.

### Gate 2: Enterprise context integration

- OpenMetadata plus direct/dbt providers pass the same conformance contract.
- Correct dataset appears in top three for at least 90% of the pilot question
  set.
- Metadata quality determines automatic, review, clarification, or refusal
  state.
- A catalog outage degrades safely and never bypasses cached policy expiry.

### Gate 3: Trust and execution

- Every outcome has complete replayable evidence.
- Unauthorized execution and cross-tenant leakage are zero in the adversarial
  suite.
- High-risk and exploratory paths require approval.
- Model or prompt changes cannot ship when an offline release gate regresses.

### Gate 4: Enterprise pilot

- Customer SSO and private data-plane execution operate end to end.
- Load, failure, backup, restore, rollback, and incident drills pass.
- P95 latency and warehouse-cost budgets are agreed with the design partner.
- Security review and penetration-test remediation are complete.
- The customer accepts the authoritative question scorecard.

### Gate 5: General availability

- A second customer onboards without custom product code.
- Published SLOs have at least one full proving window of production evidence.
- Support, incident, upgrade, deprecation, and disaster-recovery processes have
  named owners and measured response times.
- Compliance claims match implemented controls and retained evidence.

## 8. Initial Parallel Execution Waves

### Wave 0: Single-owner baseline

1. `EA-001` owns deterministic fixtures.
2. `EA-002` fixes known semantic defects after fixture approval.
3. `EA-070` may run in parallel because it produces customer requirements, not
   shared code.

Do not parallelize changes to current metric definitions before `EA-001` fixes
the expected results.

### Wave 1: Parallel foundations

- Lane A: `EA-003` AST validation.
- Lane B: `EA-004` and `EA-005` public contract v2.
- Lane C: `EA-060` evaluation harness.
- Lane D: `EA-072` initial data-flow and security inventory.

The contract lane has exclusive ownership of
`packages/platform_contracts/analytics.py`.

### Wave 2: Semantic core

- Lane A: `EA-010` and `EA-011` semantic contract and registry.
- Lane B: `EA-012` analytical intent after `EA-010` stabilizes.
- Lane C: `EA-020` provider protocols after `EA-010` stabilizes.
- Lane D: `EA-006` analytics persistence baseline.

### Wave 3: Spikes and adapters

- Lane A: `EA-013` Cube/internal compiler spike.
- Lane B: `EA-021` direct inspection provider.
- Lane C: `EA-022` dbt provider.
- Lane D: `EA-023` OpenMetadata adapter.
- Lane E: `EA-061` customer eval format.

### Wave 4: End-to-end trusted path

- `EA-014` through `EA-016` establish compilation and policy injection.
- `EA-024` through `EA-026` establish metadata gating.
- `EA-030` through `EA-033` establish planning and outcome decisions.
- `EA-034` can begin after the v2 evidence contract stabilizes.

### Wave 5: Enterprise platform

Identity, audit, data-plane, observability, and approval lanes can proceed in
parallel behind frozen v2 and policy contracts. Merge order is identity,
policy, compiler enforcement, execution gateway, then user-facing approval.

## 9. Delegating Work to Coding Models

Using multiple models makes sense for this program when tasks are bounded,
testable, and isolated. Models should accelerate implementation and verification,
not independently redefine architecture or approve security controls.

### Recommended operating model

| Role | Responsibility |
|---|---|
| Human product/architecture owner | Approves scope, ADRs, customer semantics, risk, and releases |
| Orchestrator model | Maintains dependency graph, prepares task packets, checks integration state |
| Implementer model | Changes one bounded component and its tests in an isolated worktree |
| Adversarial reviewer model | Reviews behavior, security, failure modes, and missing tests without editing first |
| Integration owner | Merges in dependency order, resolves contract conflicts, runs full gates |

### Suitable delegated tasks

- Provider adapters against a frozen protocol and recorded fixtures.
- Contract serialization, migration, and conformance tests.
- SQL AST rules with an explicit malicious-query corpus.
- Evaluation runners, report generation, and CI wiring.
- OpenTelemetry instrumentation and dashboards against named signals.
- Documentation, runbooks, SDK generation, and test fixture expansion.
- UI components against a frozen v2 API contract.

### Keep under direct senior ownership

- Semantic contract shape and compiler selection.
- Metric meaning, grain, join approval, and customer-specific policy.
- Authentication, authorization, tenant isolation, and cryptographic design.
- Destructive migrations and production data handling.
- Compliance representations and final release approval.
- Cross-cutting refactors touching multiple product boundaries.

### Concurrency rules

1. One task ID, branch, and worktree per delegated model.
2. Branch names use `codex/ea-<id>-<short-name>`.
3. A task packet owns an explicit file set. Two active tasks must not own the
   same mutable file.
4. Shared contracts, migrations, dependency manifests, and CI workflows have
   one active owner at a time.
5. Each task must include tests, validation commands, rollback notes, and an
   updated status record.
6. Implementation and adversarial review should use different model sessions.
7. Merge only after the task-local gate and the current stage gate pass.
8. Rebase or refresh context before review; models must not rely on an old
   repository snapshot.

### Model-ready task packet template

````markdown
# Task EA-___: <outcome>

## Objective
One observable outcome, not a broad theme.

## Context
- Relevant ADRs and contracts:
- Current behavior:
- Why this task exists:

## Allowed scope
- Files/directories owned by this task:
- Public interfaces that may change:

## Out of scope
- Explicitly forbidden refactors or product areas:

## Required behavior
1. ...
2. ...

## Acceptance tests
- Given/when/then behavior:
- Failure and security cases:
- Compatibility expectations:

## Validation commands
```text
<exact lint, unit, integration, and contract commands>
```

## Deliverables
- Code and tests
- ADR/docs/update where required
- Summary of risks and unresolved questions

## Stop conditions
- Contract ambiguity
- Required secret/customer data unavailable
- Change would cross an unowned boundary
````

### Required handoff from every model

- Task ID and commit SHA.
- Files changed and public behavior changed.
- Commands run and exact pass/fail result.
- Assumptions made.
- Security or data-handling impact.
- Known gaps and recommended reviewer focus.

## 10. Definition of Done

A task is not done because code was generated. It is done only when:

- Acceptance behavior and failure modes are covered by deterministic tests.
- Public contracts are versioned and documented.
- Tenant, security, privacy, and audit impact has been evaluated.
- Logs and errors contain no secrets, prompts with restricted data, or raw
  result sets unless explicitly permitted.
- Observability is added for new production behavior.
- Migrations include rollback or forward-recovery instructions.
- Local validation passes and relevant full-product CI remains green.
- An independent reviewer has checked correctness and test gaps.
- The owning phase gate remains satisfied after integration.

## 11. Program Metrics

### Product quality

- Result accuracy for certified and exploratory question sets.
- Correct dataset/table top-1 and top-3 retrieval.
- Clarification precision and unnecessary-clarification rate.
- Refusal correctness for unsupported and unauthorized questions.
- User correction rate and repeat-query consistency.

### Trust and security

- Policy enforcement and audit completeness: target 100%.
- Cross-tenant or unauthorized data exposure: target zero.
- Certified answers with source, metric, filter, freshness, and version
  evidence: target 100%.
- Time from semantic change to evaluation and certification.

### Reliability and cost

- Query availability and p50/p95/p99 latency by stage.
- Warehouse bytes scanned, execution time, and spend by tenant.
- Model tokens, latency, failure, fallback, and cost by version.
- Cancellation success, timeout rate, queue time, and concurrency saturation.

### Delivery

- Task cycle time, review escape rate, rollback rate, and flaky-test rate.
- Percentage of delegated changes accepted without architectural rework.
- Time to onboard a new dataset, catalog provider, and customer tenant.

## 12. Required Architecture Decisions

Record these as ADRs before their implementation dependency begins:

1. `ADR-EA-001`: Canonical semantic contract and ownership model.
2. `ADR-EA-002`: Cube Core versus narrow internal compiler.
3. `ADR-EA-003`: Metadata provider normalization and cache consistency.
4. `ADR-EA-004`: Analytics control-plane/data-plane data boundary.
5. `ADR-EA-005`: Identity broker, SAML, OIDC, and SCIM strategy.
6. `ADR-EA-006`: Policy engine and warehouse-policy reconciliation.
7. `ADR-EA-007`: Audit immutability, retention, and customer export.
8. `ADR-EA-008`: v2 API compatibility and v1 retirement policy.
9. `ADR-EA-009`: Model/provider routing, failover, and data-processing policy.
10. `ADR-EA-010`: Enterprise deployment tiers and supported topologies.

## 13. Immediate Next Actions

Execute these in order:

1. Approve this roadmap as the analytics program baseline.
2. Dispatch the prepared `EA-001`, `EA-003`, `EA-004`, `EA-060`, and `EA-070`
   packets from [Enterprise Analytics Task Packets](execution/enterprise-analytics/README.md).
3. Assign one owner to v2 contracts and prevent parallel edits to the v1 file.
4. Build canonical split-payment and multi-item fixtures before changing metric
   SQL.
5. Recruit one design partner with a named warehouse, identity provider,
   catalog state, and 25-50 authoritative business questions.
6. Complete the compiler spike before committing to Cube or expanding the
   current direct-SQL engine.
7. Treat OpenMetadata as the first adapter, not a runtime prerequisite.

The first engineering milestone is Gate 0, not an OpenMetadata integration.
Correct metrics, deterministic evaluation, and a contract that can represent
uncertainty are prerequisites for every enterprise feature that follows.
