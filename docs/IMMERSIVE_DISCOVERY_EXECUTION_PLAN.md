# Immersive Discovery Vertical Execution Plan

Status: IMD-001 through IMD-076 complete; IMD-077 through IMD-088 remain
optional intelligence, operations, and production-readiness follow-up work.

Audience: Engineering leads, reviewers, and delegated Luna coding sessions

Scope: A Roblox-like search and discovery demonstration built as a separate
product and deployable, using fictional or explicitly licensed data and the
shared Compass platform contracts

## 1. Executive Decision

Build one reusable discovery platform with an `immersive` domain profile. The
first product is implemented in new `services/discovery-api` and
`apps/discovery-web` deployables. It must not add discovery code to the support
API or analytics API, and it must not import either product's domain modules.

Reuse only stable platform capabilities through versioned contracts:

- OpenSearch for BM25, vector, filtered, and hybrid candidate retrieval;
- PostgreSQL for authoritative catalog, configuration, and consented events;
- object storage for raw event-lake files, generated datasets, and approved
  media assets;
- provider-neutral embedding, model, evaluation, identity, and audit contracts;
- existing control-plane conventions for tenant routing and usage controls.

The vertical owns its catalog semantics, behavior events, candidate sources,
features, ranking objectives, safety rules, API, UI, and release evidence. A
future visual-discovery or commerce-search product may reuse the platform
contracts, but this program must not pre-build Pinterest- or Amazon-specific
domain logic.

## 2. Product Outcome

The local demo lets a prospect:

1. choose a fictional player persona or start with no history;
2. search a catalog using exact, lexical, semantic, and natural-language
   queries;
3. receive a personalized home feed assembled from multiple candidate sources;
4. see safe, diverse, fresh, and socially relevant experiences;
5. inspect a concise explanation of why an item was retrieved and ranked;
6. submit impressions, clicks, plays, qualified sessions, saves, dismissals,
   and co-play events;
7. observe deterministic profile and recommendation changes without a live LLM;
8. compare lexical, hybrid, personalized, and multi-stage ranking modes through
   a repeatable local evaluation.

The demo promise is:

> Turn a large, messy experience catalog and behavioral history into relevant,
> personalized, safe discovery while preserving reproducibility, policy control,
> and ranking evidence.

## 3. Boundaries and Non-Goals

- Do not scrape Roblox, copy Roblox assets, impersonate Roblox branding, or
  claim access to Roblox proprietary algorithms or interaction data.
- Use fictional generated experiences by default. Optional public-catalog
  adapters require documented licensing, terms, rate limits, and provenance.
- Generated behavior is demonstration and load-test data, not proof of real
  customer engagement or model lift.
- Do not build ads, auctions, real-money optimization, creator payouts,
  matchmaking, chat, or game hosting in this program.
- Do not target billion-item production scale in the first release. Preserve
  provider-neutral boundaries and collect evidence before selecting a
  billion-scale vector architecture.
- Do not deploy Azure or any cloud environment. IMD-088 approves only a local
  demo unless a later program supplies cloud, privacy, security, and operational
  evidence.
- Do not let an LLM authorize content, change hard filters, fabricate catalog
  facts, or directly optimize the online ranking objective.

## 4. Data Strategy

Use three deliberately separate datasets:

| Dataset | Purpose | Storage and scale |
|---|---|---|
| Golden corpus | Human-reviewable relevance and policy truth | Checked-in JSON; at least 48 experiences, 24 users, 30 queries |
| Generated demo | Realistic interactive local product | Seeded generator; 2,500 experiences, 5,000 users, at least 250,000 events |
| Generated scale | Performance and pipeline evidence | Generated on demand; 25,000 experiences, 50,000 users, 2-5 million events |

The generator must be deterministic from a recorded seed and manifest. It
creates catalog metadata, user preferences, social relationships, exposure
context, and probabilistic outcomes. It must model exposure before action so a
click, play, or save cannot exist without a corresponding impression.

LLMs may assist with fictional titles, descriptions, tags, query variants, and
offline relevance-review suggestions. They may not generate the ground-truth
engagement labels used to claim ranking quality. Behavioral labels come from
the deterministic simulator or reviewed real-world data under a future data
agreement.

Required canonical concepts:

- experience, creator, genre, theme, modality, device support, locale, age
  rating, safety state, freshness, quality, and availability;
- user, household-safe profile, explicit preferences, consent state, friends,
  groups, and session context;
- search, impression, click, detail view, play, qualified play, playtime, save,
  dismiss, report, invite, co-play, return, and retention events;
- retrieval judgments, ranking examples, policy decisions, model versions, and
  experiment assignments.

Raw event records are append-only. Derived profiles and ranking features are
versioned and rebuildable. Personally identifying or sensitive attributes are
excluded from all checked-in and generated fixtures.

## 5. Target Architecture

```text
Fictional generator / approved catalog adapter / consented behavior events
                              |
                              v
                Canonical catalog + event store
                   PostgreSQL + object storage
                              |
                    outbox / feature jobs
                              |
              +---------------+----------------+
              |                                |
              v                                v
       OpenSearch catalog              Versioned feature views
     BM25 + vectors + filters         user / item / context / graph
              |                                |
              +---------------+----------------+
                              v
                  Multi-source candidate service
       lexical | semantic | two-tower | co-play | social | trending
                              |
                              v
                   pre-rank -> full rank -> re-rank
                              |
               safety + diversity + freshness + fairness
                              |
                              v
                     Discovery API + explanations
                              |
                              v
                     Immersive Discovery Web
```

### Request flow

```text
query or home request
  -> identity, tenant, consent, age, locale, and device context
  -> deterministic hard filters
  -> parallel bounded candidate generators
  -> candidate fusion and deduplication
  -> lightweight pre-rank
  -> learned ranker when an approved model is available
  -> multi-objective re-rank
  -> explanation and impression token
  -> client render
  -> consented interaction event
  -> offline profile/features/model evaluation
```

### LLM-assisted ranking evolution

The product gets immediate value from LLMs as bounded context engineers, not
as an unconstrained online ranker. This keeps the current demo deterministic
while leaving a measured path toward an LLM-native ranker.

```mermaid
flowchart LR
  subgraph NOW[Now: deterministic demo]
    N1[OpenSearch BM25 + vector + ACL] --> N2[Candidate fusion]
    N2 --> N3[CPU feature ranker]
    N3 --> N4[Utility + safety policy]
  end
  subgraph NEXT[Near term: context engineering]
    X1[Catalog + user + session context] --> X2[Bounded LLM enrichment]
    X2 --> X3[Versioned context/features]
    X3 --> X4[Existing CPU or learned ranker]
    X4 --> X5[Utility + safety policy]
  end
  subgraph FUTURE[Future experiment: GenRec-style]
    F1[Eligible candidates + compact context] --> F2[LLM context encoder]
    F2 --> F3[Catalog-aware scoring head]
    F3 --> F4[Utility + safety policy]
  end
  NOW -. baseline .-> NEXT
  NEXT -. offline lift + cost evidence .-> FUTURE
```

The near-term path may run offline or in shadow mode and must emit the same
versioned ranking evidence as the current path. The future path is an
experiment only: it requires catalog-constrained scoring, compacted context,
offline lift, latency/cost evidence, and an explicit model-on/model-off review
before it can affect served order. See [IMD-076](execution/immersive-discovery/IMD-076-llm-context-engineering.md).

### Ownership boundaries

| Concern | Owner |
|---|---|
| Shared request, event-envelope, model-version, and evaluation primitives | `packages/platform_contracts` |
| Immersive catalog and ranking semantics | `services/discovery-api` |
| Authoritative catalog and consented interaction records | PostgreSQL/source adapter |
| Raw generated event files and approved media | Object storage/local data directory |
| Searchable text, vectors, and filter fields | Rebuildable OpenSearch index |
| User/item/graph features | Versioned discovery feature materialization |
| Online ranking order and reason codes | Discovery ranking service |
| Product presentation and event capture | `apps/discovery-web` |

## 6. Ranking Strategy

Use a multi-stage funnel. No single model owns the full decision.

1. Retrieval maximizes recall through exact/BM25, semantic ANN, item-to-item,
   co-play, social, trending, freshness, and cold-start candidate generators.
2. Candidate fusion applies stable source quotas, deduplication, and calibrated
   source scores.
3. Lightweight pre-ranking cheaply removes weak candidates using request,
   user, item, and context features.
4. The full ranker predicts reviewed objectives such as qualified play,
   meaningful playtime, save, return, and negative feedback.
5. Multi-objective policy combines predictions without allowing monetization or
   raw popularity to dominate user satisfaction.
6. Final re-ranking enforces age/safety, availability, diversity, freshness,
   creator exposure constraints, and repetition limits.

Two-tower retrieval is a candidate source, not the final ranker. Start with a
deterministic feature ranker and a small CPU-friendly learned model. Require an
offline decision record before adding a large sequence model or GPU serving.

LLMs are optional and bounded to query interpretation, multilingual expansion,
metadata enrichment, conversational refinement, and offline judging. Every
online path has a deterministic no-LLM fallback.

For LLM-native recommendation, borrow the useful pattern of compacting user,
item, and session history into a catalog-aware context and scoring only known
candidates. Do not copy a vendor-specific architecture or claim comparable
lift from synthetic data. The first implementation milestone is the versioned
context contract and shadow/offline evaluation boundary; online LLM scoring
remains deferred.

## 7. Non-Negotiable Invariants

1. Tenant, age, safety, locale, availability, and legal filters run before any
   model score can make an item eligible.
2. Ranking cannot reintroduce an ineligible or unknown item.
3. An action event must reference a previously issued impression token, except
   explicitly typed organic events such as direct navigation.
4. Training examples preserve exposure context and avoid treating unexposed
   items as negatives.
5. Dataset, feature, embedding, model, policy, and experiment versions appear
   in evaluation and serving traces.
6. Synthetic events are visibly labeled and cannot mix with real events.
7. Raw user histories, queries, and embeddings are excluded from normal logs.
8. Profile building honors consent, deletion, and retention state.
9. Cold-start users and items have deterministic, safe fallback behavior.
10. Every candidate source, model stage, and LLM call is bounded by timeout and
    result-count limits.
11. The product works locally with fakes and generated data when OpenSearch, a
    learned model, or an LLM is unavailable.
12. The support and analytics deployables remain independently testable and do
    not import discovery modules.

## 8. Luna Execution Contract

Give each Luna session exactly one task ID, this canonical plan, and the task
packet when one exists.

The canonical task table is the program backlog, not a substitute for an
executable packet. Only tasks with a reviewed file under
`docs/execution/immersive-discovery/` may be dispatched to Luna. The integration
owner creates packets one merge wave ahead, after dependencies have fixed the
real module paths and test commands. This avoids giving a lower-cost model stale
or speculative file ownership. Wave 0 is the only dispatchable wave at plan
creation time.

- Read only the packet's `Read first` files, owned files, and direct imports.
- Change at most five implementation/test files plus one minimal export or
  documentation index unless the task explicitly allows more.
- Prefer pure functions, frozen Pydantic contracts, deterministic seeds, and
  existing repository conventions.
- Do not browse, deploy, call live Roblox or model services, download datasets,
  add a dependency, or regenerate a lock file unless the task explicitly owns
  that action.
- Do not import domain modules from `services/api` or `services/analytics-api`.
- Run targeted tests only. The integration owner runs complete gates after a
  merge wave.
- Stop after acceptance passes, create exactly one task commit, and do not
  implement the next ID.
- Keep the final handoff under 400 words: commit, files, tests, assumptions,
  risks, and next eligible IDs.

Default limits:

| Item | Limit |
|---|---:|
| Files read before editing | 8 |
| Files changed | 6 |
| New production modules | 1 |
| New focused test modules | 1 |
| External services | None unless the packet explicitly enables local OpenSearch |
| Handoff | 400 words |

Stop and escalate when a dependency is missing, a hard eligibility rule would
be weakened, source licensing is unclear, real personal data appears, more than
one public contract must change, or acceptance would require a cloud service or
credential.

### Packetization gate

Before dispatching any task after IMD-002, its packet must provide:

1. no more than eight exact `Read first` paths;
2. exact created/modified paths, including migrations and exports;
3. exact local prerequisites and whether each service must be running;
4. one targeted validation command that is known to exist at dispatch time;
5. copied dependency evidence and acceptance criteria;
6. explicit file-limit exceptions or a split into smaller numeric task IDs;
7. stop conditions and one commit subject.

Broad backlog rows such as IMD-013, IMD-024, IMD-037, IMD-056, IMD-084, and
IMD-087 require an explicit packet-level file budget. Split the backlog item
before dispatch when it cannot remain within eight changed files and two new
production modules. A reviewed packet-level exception overrides the six-file,
one-module default for that task only. Do not silently expand a Luna session.

### Path and runtime conventions

| Concern | Default owned location |
|---|---|
| Discovery Python product | `services/discovery-api/app/` |
| Discovery Python tests and fakes | `services/discovery-api/tests/` |
| Discovery migrations | `services/discovery-api/alembic/` |
| Discovery Python dependencies | `services/discovery-api/requirements.txt` |
| Discovery web product | `apps/discovery-web/` |
| Shared provider-neutral contracts only | `packages/platform_contracts/` |
| Local runtime wiring | root Compose file, `deploy/`, `scripts/`, and `Makefile` only when named by a packet |
| Generated demo/scale data | ignored local data directory; commit manifests and generators, not bulk records |

Permitted evidence remains local:

- contract, domain, fake, and pure-function tasks require no running service;
- persistence packets may require the repository's Docker PostgreSQL service;
- OpenSearch unit packets use a fake, while a packet explicitly labeled
  integration may require the local OpenSearch container;
- web unit packets use installed Node dependencies without a live API;
- Playwright and screenshot packets require the local API/web/Playwright stack
  established by IMD-080 and IMD-081;
- load, backup, restore, and cost packets use local containers, filesystem
  artifacts, and host resource measurements only.

No permitted local prerequisite authorizes a cloud resource, external dataset,
live Roblox call, or production credential.

## 9. Delivery Gates

| Gate | Exit evidence | Review |
|---|---|---|
| G0: Boundaries | ADR, golden corpus, contracts, and fakes merged | Principal architecture review |
| G1: Data | Deterministic catalog, behavior simulator, repositories, provenance, and rebuildable features pass | Data/ML review |
| G2: Retrieval | Exact, BM25, vector, hybrid, filters, and candidate-source evaluation pass | Search review |
| G3: Ranking | Training examples, model registry, inference fallback, and multi-objective re-ranking pass | Relevance/ML review |
| G4: Trust | Safety, consent, deletion, abuse resistance, explanations, and audit evidence pass | Security/product review |
| G5: Product | Search, home feed, personas, interactions, and explanations pass web/API E2E | Product acceptance |
| G6: Intelligence | Optional LLM paths improve reviewed tasks and preserve deterministic fallback | AI quality review |
| G7: Operations | Local compose, seed, evaluation, load, rebuild, and cost evidence pass | Operations review |
| G8: Demo | Local model-on/model-off demo approved; remaining production evidence explicit | Senior readiness review |

## 10. Atomic Execution Tasks

### A. Architecture, contracts, and evaluation truth

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| IMD-001 | Record the immersive discovery architecture, ownership, alternatives, and data policy | New `docs/adr/ADR-IMD-001-immersive-discovery.md` | OS-088 | ADR fixes separate deployables, shared-contract boundary, OpenSearch authority, no-scraping rule, and local-only scope |
| IMD-002 | Freeze fictional catalog, personas, queries, judgments, and policy cases | New `services/discovery-api/tests/fixtures/golden/` and one loader test | None | At least 48 experiences, 24 users, 30 queries; references valid; lexical, semantic, social, cold-start, diversity, age, safety, and no-result cases covered |
| IMD-003 | Define shared discovery envelopes and version primitives | New `packages/platform_contracts/discovery.py`, export, targeted tests | IMD-001 | Frozen provider-neutral request context, impression token, component version, and trace contracts reject extra fields |
| IMD-004 | Define immersive catalog, user, context, and eligibility contracts | New `services/discovery-api/app/domain/models.py`, targeted tests | IMD-002, IMD-003 | Models cover required canonical concepts and distinguish authoritative from derived fields |
| IMD-005 | Define versioned interaction-event contracts | New `services/discovery-api/app/events/models.py`, targeted tests | IMD-003, IMD-004 | Impression lineage, synthetic marker, consent, event time, and typed action payload validate deterministically |
| IMD-006 | Add in-memory repository, candidate-source, feature, and ranker fakes | New files under `services/discovery-api/tests/fakes/`, focused tests | IMD-004, IMD-005 | Fakes are deterministic, capture calls, simulate failure/timeout, and never bypass eligibility |
| IMD-007 | Add backend-neutral retrieval, ranking, diversity, calibration, and policy metrics | New `services/discovery-api/app/evaluation/metrics.py`, targeted tests | IMD-002, IMD-004 | Recall/MRR/nDCG, coverage, intra-list diversity, calibration, negative-feedback, and violation-rate calculations match hand-worked cases |

### B. Independent service and deterministic data plane

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| IMD-010 | Scaffold independent FastAPI discovery service and test configuration | New `services/discovery-api` baseline files | IMD-001, IMD-003 | Health test and import smoke test pass; service imports shared contracts but neither product API |
| IMD-011 | Add validated local configuration and feature flags | Discovery config and focused tests | IMD-010 | Unsafe production-like defaults fail; local fake/no-model modes are explicit |
| IMD-012 | Define catalog, event, profile, and feature repository protocols | New repository module and protocol tests | IMD-004, IMD-005, IMD-010 | Protocols expose bounded tenant-scoped reads/writes with no provider SDK types |
| IMD-013 | Add PostgreSQL persistence models and baseline migration | Discovery persistence files and migration tests | IMD-012 | Catalog/events remain authoritative, derived versions are separate, migration upgrade/downgrade passes locally |
| IMD-014 | Add deterministic fictional catalog generator and manifest | New generator module/CLI and tests | IMD-002, IMD-004 | Same seed yields byte-stable logical records; demo and scale profiles satisfy counts/distributions without PII |
| IMD-015 | Add exposure-aware behavior and social-graph simulator | New simulator module/CLI and tests | IMD-005, IMD-014 | Actions reference impressions; probabilities respond to affinity/context; retention and co-play are reproducible |
| IMD-016 | Add provenance-gated public catalog adapter contract and one fixture adapter | New adapter module and tests | IMD-004, IMD-012 | Fixture adapter records source/license/retrieval metadata; network access is disabled by default; unknown provenance fails closed |
| IMD-017 | Add append-only local event-lake writer and partition manifest | New event-lake module and tests | IMD-005, IMD-012, IMD-015 | Writes are idempotent, partitioned, synthetic-labeled, checksum-recorded, and readable without the API |
| IMD-018 | Add versioned user, item, context, social, popularity, and retention feature materialization | New feature job and tests | IMD-013, IMD-015, IMD-017 | Point-in-time feature tests prevent future leakage and rebuild to the same manifest |

### C. OpenSearch indexing and retrieval

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| IMD-020 | Record discovery index and vector strategy ADR | New discovery ADR | IMD-001, IMD-004 | ADR covers analyzers, dimensions, filters, aliases, vector engine, billion-scale reopen conditions, and fallback |
| IMD-021 | Define versioned immersive catalog mapping and compatibility check | New search mapping module and tests | IMD-004, IMD-020 | Mapping supports exact IDs, text, tags, locale/device/age/safety filters, vectors, provenance, and generation aliases |
| IMD-022 | Add provider-neutral catalog document mapper | New mapper module and tests | IMD-004, IMD-021 | Mapper is deterministic, excludes prohibited fields, and preserves source/content/permission versions |
| IMD-023 | Add bounded outbox indexing worker | New worker module and tests | IMD-013, IMD-022 | Bulk upsert, retry, checkpoint, poison record, and idempotency cases pass through a fake provider |
| IMD-024 | Add delete, tombstone, rebuild, reconciliation, and alias-swap commands | Search maintenance modules and tests | IMD-023 | Dry run, mismatch gate, rollback, and deletion evidence are deterministic |
| IMD-025 | Add scoped exact and BM25 retrieval | New lexical retrieval module and tests | IMD-006, IMD-021, IMD-022 | Exact ID/title boosts, phrase handling, filters, stable pagination, and no-result cases pass golden judgments |
| IMD-026 | Add filtered vector retrieval | New vector retrieval module and tests | IMD-006, IMD-020, IMD-022 | ANN request applies hard eligibility filters before scoring and returns only known versioned items |
| IMD-027 | Add deterministic hybrid fusion | New fusion module and tests | IMD-025, IMD-026 | RRF/source weights, deduplication, bounds, reason codes, and single-source degradation are stable |
| IMD-028 | Add deterministic query parsing and optional intent contract | New query module and tests | IMD-004, IMD-027 | Preserves exact names/IDs, extracts allowlisted constraints, handles empty/noisy input, and needs no LLM |
| IMD-029 | Add fail-closed eligibility/filter compiler | New policy filter module and tests | IMD-004, IMD-021 | Age, safety, locale, device, availability, tenant, and blocked-item cases cannot be overridden by query or score |

### D. Candidate generation and personalization

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| IMD-030 | Define candidate-source protocol, source quotas, and candidate trace | New candidates contract and tests | IMD-003, IMD-004, IMD-006 | Source outputs are bounded, versioned, eligible, and independently degradable |
| IMD-031 | Add trending, quality, and freshness candidates | New candidate source and tests | IMD-018, IMD-030 | Time decay, minimum quality, small-item normalization, and deterministic ties pass |
| IMD-032 | Add item-to-item semantic and metadata candidates | New candidate source and tests | IMD-026, IMD-030 | Similarity uses approved fields, excludes seed/blocked items, and records reason codes |
| IMD-033 | Add co-play and co-engagement graph candidates | New candidate source and tests | IMD-015, IMD-018, IMD-030 | Edge weights use qualified events, time decay, support thresholds, and no future leakage |
| IMD-034 | Add two-tower retrieval baseline and offline export contract | New retrieval model module and tests | IMD-018, IMD-030 | User/item embeddings are versioned; cold-start vectors are deterministic; ANN export is reproducible |
| IMD-035 | Add consent-aware friend and group candidates | New social source and tests | IMD-015, IMD-030 | Only consented relationships contribute; private identity and raw friend activity are absent from responses/logs |
| IMD-036 | Add user/item cold-start policy | New cold-start module and tests | IMD-014, IMD-018, IMD-030 | New users use explicit/contextual priors; new items receive bounded exploration after safety/quality gates |
| IMD-037 | Add parallel candidate orchestration, quotas, fusion, and degradation | New candidate service and tests | IMD-027, IMD-029, IMD-031 to IMD-036 | Timeout of one source does not fail the request; hard filters and global caps hold after fusion |
| IMD-038 | Add online point-in-time feature hydration | New hydration module and tests | IMD-018, IMD-037 | Missing/stale features use typed defaults and expose version/age without leaking private attributes |
| IMD-039 | Extend evaluator for source recall, overlap, coverage, and cold-start quality | Evaluation module and tests | IMD-007, IMD-037 | Report attributes gains and failures by candidate source and cohort |

### E. Multi-stage ranking

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| IMD-040 | Freeze online ranking feature and prediction contracts | New ranking models and tests | IMD-038 | User/item/context/cross features, missingness, objectives, and versions are strict and provider-neutral |
| IMD-041 | Build point-in-time training examples with exposure-aware labels | New dataset builder and tests | IMD-005, IMD-017, IMD-018, IMD-040 | Examples join only information available at impression time and distinguish skip from unexposed |
| IMD-042 | Select one CPU learned ranker from a bounded offline spike | New ranker ADR and spike report only | IMD-041 | Compares deterministic linear baseline, LightGBM, XGBoost, and neural options using fixed criteria; selects one CPU learned ranker for IMD-043, records license/install implications, and defers neural serving |
| IMD-043 | Add the approved CPU-ranker dependency | Discovery requirements/lock file and install smoke test only | IMD-042 | Exact version and license match the ADR; clean discovery-service install and import pass |
| IMD-044 | Add deterministic pre-ranker | New pre-rank module and tests | IMD-037, IMD-040 | Cheap bounded scoring reduces candidates without changing eligibility and has a no-history fallback |
| IMD-045 | Add repeatable offline ranker training command | New training module/CLI and tests | IMD-041 to IMD-043 | Fixed seed produces recorded dataset/features/metrics/artifact checksums; train/validation split is time-aware |
| IMD-046 | Add local immutable model registry and promotion states | New registry module and tests | IMD-045 | Draft/candidate/approved/deprecated lifecycle, compatibility checks, and rollback pass |
| IMD-047 | Add bounded online ranker inference with deterministic fallback | New inference module and tests | IMD-044, IMD-046 | Unknown/incompatible/timeout model falls back; output cannot add candidates or mutate eligibility |
| IMD-048 | Add reviewed multi-objective utility policy | New objective module and tests | IMD-040, IMD-047 | Combines qualified play, satisfaction, return, save, and negative signals with versioned weights and caps |
| IMD-049 | Add final safety, diversity, freshness, repetition, and creator-exposure reranker | New rerank module and tests | IMD-029, IMD-048 | Ineligible content never appears; list-level constraints pass hand-worked cases with deterministic relaxation order |
| IMD-059 | Add stage router, reason codes, score redaction, and full fallback chain | New ranking service and tests | IMD-044, IMD-047 to IMD-049 | Modes select hybrid-only/pre-rank/full-rank predictably; explanations reveal factors, not private features or model internals |

### F. Feedback, experiments, and trust controls

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| IMD-050 | Add consented interaction ingestion and impression validation | New event service and tests | IMD-005, IMD-013, IMD-059 | Duplicate/replayed/unknown impression actions are rejected or idempotent; direct navigation remains typed separately |
| IMD-051 | Add versioned short- and long-term profile builder | New profile job and tests | IMD-018, IMD-050 | Recency, explicit preference, negative feedback, and consent behavior are deterministic and deletion-aware |
| IMD-052 | Add bounded exploration policy | New exploration module and tests | IMD-036, IMD-049, IMD-051 | Exploration budget, eligibility, creator caps, seed reproducibility, and kill switch pass |
| IMD-053 | Add deterministic experiment assignment and exposure logging | New experiment module and tests | IMD-003, IMD-050 | Assignment is stable and mutually exclusive; exposure records all component versions and excludes raw histories |
| IMD-054 | Add redacted quality, latency, feature-age, and model telemetry | New telemetry module and tests | IMD-053, IMD-059 | Metrics identify stages/cohorts/versions without query text, profile vectors, or private social data |
| IMD-055 | Add offline drift, calibration, slice, and regression gates | New monitoring module and tests | IMD-007, IMD-039, IMD-044, IMD-054 | Gates cover new users/items, locale/device, genre, creator size, age band, and safety classes |
| IMD-056 | Add consent withdrawal, retention, export, and deletion workflow | New privacy module and tests | IMD-013, IMD-017, IMD-051 | Canonical and derived records are located, deleted or tombstoned, and prevented from reappearing after rebuild |
| IMD-057 | Add gaming, spam, popularity-loop, and event-poisoning defenses | New integrity module and tests | IMD-015, IMD-050, IMD-055 | Rate, duplication, impossible sequence, coordinated activity, and runaway feedback-loop fixtures are detected or bounded |
| IMD-058 | Add append-only ranking decision audit evidence | New audit module and tests | IMD-052 to IMD-057, IMD-059 | Trace records eligibility/policy/version/reason/fallback without raw personal data or provider payloads |

### G. Product API and local experience

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| IMD-060 | Add typed search endpoint | Discovery routes and tests | IMD-028, IMD-029, IMD-059 | Returns bounded results, explanations, versions, and impression tokens; invalid context fails closed |
| IMD-061 | Add typed personalized home endpoint | Discovery routes and tests | IMD-037, IMD-052, IMD-059 | Persona/no-history modes return safe diverse results with source and fallback evidence |
| IMD-062 | Add interaction, feedback, and explanation endpoints | Discovery routes and tests | IMD-050, IMD-058 | Events require valid lineage/consent; explanations are redacted and reference the served decision |
| IMD-063 | Scaffold independent React discovery app | New `apps/discovery-web` baseline | IMD-010, IMD-060 to IMD-062 | Typecheck/unit test/build pass; app imports neither support nor analytics product code |
| IMD-064 | Build search and filter experience | Discovery web search files/tests | IMD-063 | Exact and natural queries, filters, empty/error/loading states, pagination, and keyboard use pass |
| IMD-065 | Build personalized home feed and item details | Discovery web feed files/tests | IMD-063 | Stable layout shows real generated content, reasons, safety/age metadata, and source diversity |
| IMD-066 | Add fictional personas, cold-start mode, and local feedback controls | Discovery web demo files/tests | IMD-051, IMD-063 to IMD-065 | Persona changes are explicit; interactions update later requests; synthetic/demo labeling remains visible |
| IMD-067 | Add ranking-inspector and evaluation comparison view | Discovery web inspection files/tests | IMD-039, IMD-054, IMD-059, IMD-063 | Operator can compare retrieval/ranking modes and inspect stages without exposing private feature values |
| IMD-068 | Add responsive accessibility and visual-regression coverage | Discovery web tests | IMD-064 to IMD-067 | Desktop/mobile screenshots have no overlap/overflow; keyboard, focus, reduced-motion, and contrast checks pass |
| IMD-069 | Add API/web end-to-end discovery journeys | Discovery Playwright tests | IMD-060 to IMD-068 | Search, home, cold start, persona, feedback adaptation, safety exclusion, and degraded-mode journeys pass |

### H. Optional bounded LLM intelligence

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| IMD-070 | Define structured discovery-intent and query-expansion contract | New intelligence models and tests | IMD-028 | Strict schema preserves exact terms, caps expansions, and cannot modify identity or eligibility context |
| IMD-071 | Add scripted fake and bounded intent adapter | New intelligence adapter/fake tests | IMD-006, IMD-070 | Malformed/timeout/injection outputs fall back to deterministic query parsing |
| IMD-072 | Add provenance-preserving metadata enrichment workflow | New enrichment module and tests | IMD-004, IMD-016, IMD-071 | Generated tags/descriptions are draft, attributed, schema-valid, reviewable, and excluded from authoritative facts until approved |
| IMD-073 | Add conversational discovery refinement | New refinement module and tests | IMD-060, IMD-070, IMD-071 | Follow-up constraints remain bounded; session memory is explicit; deterministic search remains available |
| IMD-074 | Add offline LLM relevance-judge workflow | New judge module and tests | IMD-002, IMD-007, IMD-071 | Judge proposes labels with prompt/model versions; human labels remain authoritative; no online rank dependency |
| IMD-075 | Add prompt-injection, token-budget, cache, routing, and kill-switch policy | New intelligence safety module and tests | IMD-071 to IMD-074 | Catalog text remains untrusted data; calls are capped/versioned/redacted; kill switch immediately restores no-LLM mode |
| IMD-076 | Freeze LLM context-engineering contract and GenRec experiment boundary | `docs/adr/ADR-IMD-076-llm-context-engineering.md` and evaluation checklist | IMD-039, IMD-047, IMD-058, IMD-075 | Context fields, compaction, candidate binding, provenance, budgets, shadow mode, and promotion gates are versioned; no online LLM ranker is enabled |

### I. Local operations and release evidence

| ID | Deliverable | Owned files | Depends on | Acceptance evidence |
|---|---|---|---|---|
| IMD-080 | Add local Docker Compose profile and health checks | Compose/discovery deployment files and tests | IMD-010, IMD-013, IMD-021, IMD-063 | Discovery API/web/Postgres/OpenSearch start without altering support/analytics profiles |
| IMD-081 | Add one-command local seed, rebuild, and reset workflow | New scripts/Make targets and tests | IMD-014, IMD-015, IMD-017, IMD-018, IMD-024, IMD-080 | Same seed rebuilds the same manifest; command prints exact destructive scope before local reset |
| IMD-082 | Add repeatable end-to-end offline evaluation command and report | New evaluation CLI and versioned report | IMD-007, IMD-039, IMD-055, IMD-059, IMD-081 | Report compares lexical/hybrid/personalized/full-rank modes and records data/model/policy versions |
| IMD-083 | Add local load and capacity test | New load plan/script and report | IMD-069, IMD-081 | Demo and scale profiles report throughput, p50/p95/p99, errors, stage timing, and resource use without unsupported claims |
| IMD-084 | Add adversarial isolation, eligibility, privacy, and abuse suite | New security E2E test | IMD-056 to IMD-058, IMD-069, IMD-075 | Cross-tenant, under-age, blocked content, event replay, injection, deletion, and log-redaction cases pass |
| IMD-085 | Add local backup, restore, rebuild, and index-rollback drill | New runbook/script/evidence record | IMD-024, IMD-056, IMD-080 | Canonical restore and derived rebuild preserve counts/checksums and deleted content does not reappear |
| IMD-086 | Add staging-scale cost and architecture model without deployment | New cost document/calculator tests | IMD-083 | Separates storage, indexing, retrieval, model inference, telemetry, and optional LLM assumptions; no Azure resources created |
| IMD-087 | Add local demo acceptance script, screenshots, and evidence record | New demo script and execution record | IMD-066 to IMD-069, IMD-082 to IMD-085 | Model-on/model-off and learned-ranker/fallback scenarios pass from a clean local seed |
| IMD-088 | Complete immersive discovery readiness review | New readiness record | IMD-050 to IMD-087 | No open critical/high local-demo issue; metrics, limitations, synthetic-data caveat, and production evidence gaps are explicit |

## 11. Dispatch Waves

| Wave | Luna tasks that may run concurrently | Merge and review rule |
|---|---|---|
| 0 | IMD-001, IMD-002 | Merge both; review architecture and golden truth before contracts |
| 1 | IMD-003 | Shared envelope must merge before domain contracts |
| 2 | IMD-004 | Freeze immersive domain vocabulary before events/repositories |
| 3 | IMD-005, IMD-007, IMD-010, IMD-020 | Separate ownership; merge contract work before implementation consumers |
| 4 | IMD-006, IMD-011, IMD-012, IMD-021 | Run G0 after fakes and service baseline pass |
| 5 | IMD-013, IMD-014, IMD-016, IMD-022, IMD-030 | Non-overlapping persistence, data, mapping, and candidate contracts |
| 6 | IMD-015, IMD-023, IMD-025, IMD-026 | Merge simulator before event-lake and features; retrieval uses fakes |
| 7 | IMD-017, IMD-024, IMD-027, IMD-028, IMD-029 | Run OpenSearch integration review after maintenance and retrieval merge |
| 8 | IMD-018 | Run G1 data review after point-in-time materialization passes |
| 9 | IMD-031, IMD-032, IMD-033, IMD-034, IMD-035, IMD-036 | Candidate sources own separate modules and may run in parallel |
| 10 | IMD-037 | Candidate orchestration merges after every source has a conformance result |
| 11 | IMD-038 | Feature hydration freezes ranking input ownership |
| 12 | IMD-039, IMD-040 | Run G2 after candidate evaluation; ranking contract can proceed independently |
| 13 | IMD-041, IMD-044 | Training examples and deterministic pre-rank have separate ownership |
| 14 | IMD-042 | Human reviews the CPU-ranker ADR before any dependency change |
| 15 | IMD-043 | Install only the dependency approved by IMD-042 |
| 16 | IMD-045 | Merge repeatable training before registry and serving |
| 17 | IMD-046 | Registry lifecycle must merge before inference |
| 18 | IMD-047 | Learned inference and fallback review |
| 19 | IMD-048 | Human approves multi-objective utility policy |
| 20 | IMD-049 | Trust review final list constraints and relaxation order |
| 21 | IMD-059 | Merge stage routing and run G3 ranking review |
| 22 | IMD-050, IMD-060 | Event ingestion and search-route ownership do not overlap |
| 23 | IMD-051, IMD-053 | Profile and experiment work start after event ingestion |
| 24 | IMD-052, IMD-054, IMD-056 | Exploration, telemetry, and privacy have separate ownership |
| 25 | IMD-055, IMD-061 | Monitoring and personalized-home routing consume completed features/policy |
| 26 | IMD-057 | Integrity defenses consume completed monitoring gates |
| 27 | IMD-058 | Run G4 after all audit dependencies through IMD-057 have merged |
| 28 | IMD-062 | Freeze the complete API before product UI work |
| 29 | IMD-063 | Scaffold web only after IMD-060 through IMD-062 merge |
| 30 | IMD-064, IMD-065, IMD-066, IMD-067 | Web tasks may run concurrently only with disjoint files recorded in packets |
| 31 | IMD-068 | Visual and accessibility review before E2E |
| 32 | IMD-069 | Run G5 product acceptance |
| 33 | IMD-070 | Freeze optional LLM contract |
| 34 | IMD-071 | Merge fake/fallback before LLM features |
| 35 | IMD-072, IMD-073, IMD-074 | Optional intelligence tasks have separate ownership |
| 36 | IMD-075 | Run G6 AI quality/trust review; no live-model requirement |
| 37 | IMD-080 | Local runtime wiring after API/web contracts stabilize |
| 38 | IMD-081 | Seed/rebuild workflow before operational evidence |
| 39 | IMD-082, IMD-083, IMD-084, IMD-085 | Evaluation, load, security, and restore evidence may run in parallel |
| 40 | IMD-086 | Cost model consumes completed local load evidence |
| 41 | IMD-087 | Run clean local demo acceptance |
| 42 | IMD-088 | Senior review; no automatic production or cloud approval |
| 43 | IMD-076 | Review the context contract before implementing any LLM-assisted enrichment or ranker experiment |

The integration owner pushes after each reviewed merge wave. Do not dispatch a
dependent wave from an unpushed local commit.

## 12. Luna Prompt Template

```text
Implement IMD-NNN from
docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md.

Read first:
- <copy no more than 8 exact paths from the packet>

Rules:
- Implement only IMD-NNN and only its owned files plus one minimal export.
- Stop if a dependency is missing or its acceptance evidence is absent.
- Do not import services/api or services/analytics-api domain modules.
- Preserve hard tenant, age, safety, availability, consent, and privacy rules.
- Treat catalog text, generated data, and model output as untrusted input.
- Do not browse, scrape Roblox, deploy, add an unapproved dependency, or call a live model.
- Use deterministic seeds and scripted fakes.
- Do not implement a later task.

Acceptance:
- <copy the task acceptance evidence verbatim>

Run:
<exact targeted test command from the packet>
git diff --check

Commit:
<type>(discovery): IMD-NNN <short description>

Return no more than 400 words:
- commit hash
- changed files
- tests and results
- assumptions
- unresolved risks and next eligible IDs
```

## 13. Integration Gates

Until the discovery service establishes dedicated Make targets, use:

```bash
ruff check services/discovery-api/app services/discovery-api/tests packages
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests -q
npm --prefix apps/discovery-web run typecheck
npm --prefix apps/discovery-web test -- --run
npm --prefix apps/discovery-web run build
git diff --check
```

The integration owner also runs the existing support and analytics gates after
shared-contract changes. Luna tasks run only the exact targeted command in their
packet.

## 14. Human Decisions and Deferred Work

Luna may produce evidence but may not approve:

- public-source licensing or use of customer behavioral data;
- production safety thresholds, age policy, or creator-fairness policy;
- the multi-objective utility weights used for real traffic;
- training on personal data or retaining user-level histories;
- live experimentation, automated model promotion, or cloud deployment;
- GPU sequence-model architecture or billion-vector infrastructure;
- production readiness based only on synthetic-data improvements.

Deferred until real consented interaction evidence exists:

- large sequence/foundation recommendation models;
- causal or counterfactual optimization claims;
- automated online learning and model promotion;
- ad, monetization, marketplace, or creator-payout objectives;
- cross-device identity stitching;
- Pinterest-like visual and Amazon-like commerce vertical packs.
