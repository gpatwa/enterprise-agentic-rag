# ADR-IMD-001: Immersive Discovery Vertical Architecture

Status: Accepted for local, pre-customer demonstration planning
Date: 2026-08-23

## Context and Product Outcome

The product needs a Roblox-like immersive discovery demonstration: a user can
search a fictional experience catalog, receive a personalized home feed, and
understand why safe and diverse items were selected. The demonstration must
exercise exact, lexical, semantic, social, and personalized retrieval together
with multi-stage ranking, while remaining reproducible on local infrastructure.

This is a new product vertical. It is not a claim about Roblox's proprietary
systems, data, ranking algorithms, or production scale. The canonical scope,
milestones, and local-only evidence gates are defined in the [Immersive
Discovery Execution Plan](../IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md).

## Decision

Build one reusable discovery platform with an immersive domain profile. The
immersive product owns its domain semantics and is deployed independently as:

- `services/discovery-api`: catalog, events, candidate generation, ranking,
  policy evaluation, explanations, and discovery APIs.
- `apps/discovery-web`: immersive discovery experience, persona selection,
  result presentation, and consented interaction capture.

Discovery code must not be added to, or imported from, the support API or the
analytics API. The product may depend on stable, versioned, provider-neutral
contracts in `packages/platform_contracts`; shared contracts must not contain
immersive ranking policy or product UI assumptions. Future Pinterest-like or
commerce-like products may use the platform contracts, but each receives its
own domain profile and deployables.

OpenSearch is the derived search plane for exact terms, BM25, vectors, hybrid
candidate retrieval, and mandatory filters. PostgreSQL and approved source
adapters remain authoritative. Local files or object storage hold append-only
raw generated events and approved media. Derived indexes can be deleted and
rebuilt from canonical data. This follows the [OpenSearch enterprise search
ADR](ADR-OS-001-opensearch-enterprise-search.md).

## Ownership and Authority

| Concern | Authority and owner |
|---|---|
| Catalog truth, creator metadata, availability, provenance | PostgreSQL or an approved catalog adapter; immersive domain owns the schema and validation |
| Raw behavior events | Append-only local event files/object storage, with canonical event records in the discovery event store |
| Event lineage and consent | Discovery event contract and event store; every served action references an impression token unless explicitly typed as organic navigation |
| Searchable text, vectors, and filter fields | Rebuildable versioned OpenSearch index; never the source of customer truth |
| User, item, social, and context features | Versioned discovery feature materializations, rebuildable from canonical events and catalog data |
| Ranking models and model versions | Discovery ranking service and its model registry/evaluation records; no model bypasses eligibility policy |
| Hard eligibility, age, safety, privacy, and exposure rules | Discovery policy module and policy versions; policies run before model scoring and cannot be weakened by an LLM |
| Explanations and reason codes | Discovery ranking response, tied to candidate source, feature/model versions, and policy decision |
| Audit evidence | Append-only discovery audit records containing request, policy, candidate-source, model, dataset, and experiment versions without raw sensitive history |
| UI and interaction capture | `apps/discovery-web`, using the versioned discovery event contract |
| Shared primitives | `packages/platform_contracts`, limited to provider-neutral envelopes, identity/context, event, model-version, evaluation, and audit primitives |

The catalog and event store are canonical. Features, embeddings, model outputs,
OpenSearch documents, explanations, and experiment assignments are derived and
must carry versions sufficient for deterministic rebuild and evaluation.

## Retrieval and Ranking Flow

Each request first resolves tenant, consent, age, locale, device, and session
context. Deterministic hard filters then establish eligibility. Bounded
candidate sources run in parallel:

1. exact ID and field matching plus OpenSearch BM25;
2. semantic vector retrieval;
3. two-tower or item-to-item retrieval when an approved model exists;
4. social/co-play, trending, freshness, and cold-start sources.

Candidates are deduplicated and fused with stable source quotas, then passed
through a lightweight pre-ranker, an approved full ranker, and a final policy
re-ranker. The final stage enforces safety, age, availability, diversity,
freshness, creator exposure, repetition, and negative-feedback constraints.
The ranker optimizes reviewed objectives such as qualified play, meaningful
playtime, saves, return behavior, and negative feedback; raw popularity or
monetization cannot dominate user satisfaction.

An ineligible item cannot be reintroduced by a later stage. Every response
includes an impression token and enough versioned evidence to explain the
result without exposing sensitive user history.

### Ranking evolution boundary

The current serving path is intentionally deterministic and catalog-bound:

```mermaid
flowchart LR
  A[OpenSearch BM25 + vector + ACL] --> B[Candidate fusion]
  B --> C[CPU or approved learned ranker]
  C --> D[Utility, safety, diversity, freshness]
  D --> E[Discovery response + audit]
```

LLMs can improve the next stage by compacting and enriching catalog, user, and
session context before ranking. That path is allowed offline or in shadow mode
only, with a versioned context contract and deterministic fallback:

```mermaid
flowchart LR
  A[Catalog + user + session history] --> B[Bounded LLM context adapter]
  B --> C[Versioned compact context]
  C --> D[Existing ranker]
  D --> E[Policy + audit]
  B -. timeout, budget, kill switch .-> F[Deterministic context fallback]
  F --> D
```

A later GenRec-style experiment may use a compact context encoder and a
catalog-aware scoring head, but it is not part of the current online decision
path. It must score only eligible retrieved candidates, preserve reason and
version evidence, and pass offline relevance, policy, latency, cost, and
model-on/model-off gates before any traffic exposure. Synthetic demo data can
validate plumbing and reproducibility; it cannot establish customer lift. The
decision is tracked in [IMD-076](../execution/immersive-discovery/IMD-076-llm-context-engineering.md).

## Safety, Privacy, and Audit Constraints

- Tenant, age, consent, locale, safety, availability, and legal filters are
  deterministic and fail closed.
- Profiles honor consent, retention, deletion, and household-safe boundaries.
- Checked-in fixtures contain no personal or sensitive attributes.
- Synthetic events are marked as synthetic and cannot be mixed silently with
  real events or used as evidence of customer lift.
- Candidate sources, rankers, policy checks, and model calls have bounded
  timeouts and result counts; deterministic fallbacks remain available.
- Audit records include policy, dataset, feature, embedding, model, and
  experiment versions, but avoid raw histories, sensitive queries, and full
  embeddings in normal logs.

## Data and LLM Policy

Checked-in and default demo data is fictional and generated from a recorded
seed. A deterministic simulator may create exposure, click, play, session,
save, co-play, return, and retention outcomes, but generated behavior is only
demonstration/load-test evidence. It is not ground truth for real engagement
or ranking lift. Human-reviewed relevance and policy judgments remain the
quality reference.

The product must not scrape Roblox, copy Roblox assets, impersonate its brand,
or use proprietary interaction data. Any public catalog adapter requires
documented provenance, terms, rate limits, and explicit licensing review before
use. This ADR does not approve a particular external dataset or license.

LLMs may assist with fictional metadata, bounded query interpretation,
multilingual expansion, conversational refinement, offline judging, and
versioned context compaction for ranking experiments. An LLM cannot alter
identity, consent, hard eligibility, safety filters, candidate membership, or
audit truth. It cannot become the online ranker of record until a later ADR
approves the evidence. Every LLM path has a deterministic no-LLM fallback.

## Alternatives Considered

| Alternative | Decision | Tradeoff |
|---|---|---|
| Extend the support API | Rejected | Fast initial reuse, but couples unrelated domain models, release cycles, ranking objectives, and data retention rules. It would undermine independent deployment and make the support product the accidental owner of discovery semantics. |
| Build three separate platforms for Roblox-like, Pinterest-like, and Amazon-like products | Rejected | Maximizes domain freedom but duplicates ingestion, retrieval, feature, evaluation, policy, audit, and operations infrastructure before any product has proven demand. |
| Build one generic platform with one universal ranker | Rejected | Shares infrastructure too aggressively. Immersive play quality, visual saves, and commerce conversion have different entities, labels, constraints, and objective functions; a universal ranker would hide those differences and weaken evaluation. |
| Shared platform with domain profiles | Selected | Reuses provider-neutral contracts and retrieval/ranking infrastructure while keeping catalog semantics, labels, features, objectives, policies, APIs, and UIs domain-owned. It has more contract discipline than a single product but preserves the best path to future verticals. |

## Local Rollout and Evaluation Gates

This decision authorizes documentation and later local implementation only. The
initial gates are:

1. freeze a human-reviewable fictional golden corpus;
2. validate shared contracts and immersive domain models;
3. prove deterministic indexing, hybrid retrieval, candidate fusion, ranking,
   safety, diversity, cold-start, and event lineage with fakes or local
   services;
4. compare lexical, hybrid, personalized, and multi-stage modes using
   repeatable offline cases;
5. demonstrate model-on/model-off behavior and record limitations;
6. complete a local readiness review before calling the demo ready.

No cloud resource, external data download, live model service, or production
traffic is authorized by this ADR. Local OpenSearch evidence may be used where
an execution packet explicitly permits it. OS-088 evidence remains a local
planning dependency; production sign-off is outside this decision.

## Deferred Decisions

The following remain open until measured evidence and a later ADR exist:

- public or customer-provided data agreements and licensing;
- production cloud topology, residency, security, backup, and SLOs;
- billion-item vector/index architecture and capacity economics;
- GPU or large sequence-model serving;
- online LLM ranking or a GenRec-style catalog-aware scoring head;
- creator monetization, ads, auctions, matchmaking, chat, and game hosting;
- whether a future vertical requires a separate specialized retrieval backend.

## Revisit Conditions

Reopen this ADR if a design partner requires data or policy obligations that
cannot be represented by the shared contracts, if independent deployables
create unacceptable operational duplication, if measured local retrieval or
ranking quality fails the agreed gates, or if a licensed production dataset
requires a materially different authority, privacy, or residency model.

## References

- [Immersive Discovery Execution Plan](../IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md)
- [LLM Context Engineering ADR](ADR-IMD-076-llm-context-engineering.md)
- [OpenSearch Enterprise Search ADR](ADR-OS-001-opensearch-enterprise-search.md)
- [OpenSearch Execution Plan](../ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md)
- [OpenSearch Operations Review](../execution/enterprise-search/OS-080-088-operations-review.md)
- [Platform Architecture](../architecture.md)
