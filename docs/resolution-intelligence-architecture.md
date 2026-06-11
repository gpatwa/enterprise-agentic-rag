# Customer Support Resolution Intelligence Architecture

## Architecture Decision

Resolution Intelligence is a domain-specific workflow built on the existing Compass control-plane/data-plane architecture. It should remain helpdesk-neutral, evidence-first, and safe for enterprise pilots.

The first production-quality path is:

connectors -> canonical support data -> durable sync/index jobs -> repeat issue clustering -> hybrid retrieval -> evidence-backed playbook -> KB gap recommendation -> deflection measurement.

## Current V1 Components

Backend:
- `support_integrations`: connector catalog and connection state for Zendesk/Intercom.
- `support.sync`: provider sync runners.
- `support.models`: canonical support entities for tickets, comments, articles, sync runs, index records, and jobs.
- `support.jobs`: durable job state and worker execution.
- `support.indexer`: support-specific vector index for tickets, comments, and articles.
- `support.insights`: repeat-ticket clustering from normalized support tickets.
- `support.resolver`: cited resolution generation from the support index.
- `support.workflow`: repeat-cluster workflow assembly for playbook, KB gap, and deflection estimate.

Frontend:
- `/support`: local operating console for demo seed, sync/index, repeat insights, playbook generation, search, and resolution.

## Data Flow

```mermaid
flowchart LR
    Helpdesk[Zendesk / Intercom] --> Sync[Support sync runner]
    Demo[Demo seed data] --> Store[(Canonical support DB)]
    Sync --> Store
    Store --> Jobs[Durable sync/index jobs]
    Jobs --> Indexer[Support indexer]
    Indexer --> Vector[(Qdrant support index)]
    Store --> Clusters[Repeat issue clustering]
    Clusters --> Workflow[Resolution workflow builder]
    Vector --> Resolver[Cited resolver]
    Resolver --> Workflow
    Workflow --> UI[/support workflow panel]
    Workflow --> Gaps[KB and macro gap recommendation]
    Workflow --> ROI[Deflection estimate]
```

## Domain Model

V1 logical entities:
- `IssueCluster`: repeated support issue derived from tags, subjects, categories, and ticket status mix.
- `IssueSignature`: normalized signals that identify the issue cluster.
- `EvidenceSource`: ticket, comment, or article chunk used to support a recommendation.
- `ResolutionPlaybook`: agent-reviewable instructions and customer response draft.
- `KnowledgeGap`: missing or stale macro/help-center/product guidance required to deflect repeats.
- `DeflectionEstimate`: estimated deflectable repeat tickets in the analyzed sample with assumptions.

These are initially computed at request time. Persisting accepted playbooks and measuring before/after impact should be a follow-up milestone.

## API Surface

Existing:
- `POST /api/v1/support/demo/seed`
- `POST /api/v1/support/jobs/sync-index`
- `POST /api/v1/support/index`
- `GET /api/v1/support/insights/repeats`
- `GET /api/v1/support/search`
- `POST /api/v1/support/resolve`

Added for v1 workflow:
- `POST /api/v1/support/insights/repeats/workflow`

Request shape:

```json
{
  "cluster_id": "tag:export|timeout",
  "provider": "zendesk",
  "status": null,
  "limit": 200,
  "min_count": 2
}
```

Response shape:

```json
{
  "workflow": {
    "cluster": {},
    "query": "How have we resolved export timeout issues?",
    "playbook": {},
    "knowledge_gap": {},
    "deflection_estimate": {}
  }
}
```

## Evidence Rules

V1 evidence-gating rules:
- If there are no matches, confidence is low and the next action is human routing.
- If there are cited matches and at least two strong results, the playbook can be marked ready for agent review.
- If no article evidence exists but solved tickets exist, recommend creating a KB article or macro.
- If article evidence exists but repeats continue, recommend refreshing the article or exposing it earlier in the support flow.
- Customer-facing drafts remain review-required until private/public source filtering and deterministic citation verification are complete.

Future production rules:
- enforce public/private source visibility before drafting customer text;
- require claim-to-source span verification;
- block unsupported claims;
- store accepted playbooks with corpus/index version;
- evaluate precision@k, recall@k, citation coverage, and unsupported-claim rate in CI.

## Retrieval Strategy

Current local v1 uses vector retrieval for support memory. The next architecture upgrade should add:
- lexical/BM25 retrieval for exact error strings, IDs, product names, and plan names;
- reciprocal rank fusion or weighted hybrid ranking;
- cross-encoder reranking;
- retrieval trace output with vector score, lexical score, rerank score, source ID, source type, and visibility.

## Security And Governance

Required posture:
- tenant-scoped storage, sync, indexing, and retrieval;
- audit events for sync, index, resolve, and workflow generation;
- no direct customer reply automation in v1;
- no customer-facing output from private/internal evidence until visibility filtering is implemented;
- control-plane/data-plane split remains the enterprise deployment direction.

## Milestones

Milestone 1: Local workflow
- demo seed;
- repeat clusters;
- playbook generation;
- KB gap recommendation;
- deflection estimate.

Milestone 2: Retrieval quality
- BM25/full-text search;
- hybrid fusion;
- reranking;
- evidence trace.

Milestone 3: Trust gate
- source visibility filtering;
- deterministic citation verification;
- unsupported-claim blocking;
- golden eval suite.

Milestone 4: Pilot readiness
- Zendesk sandbox validation;
- Intercom sandbox validation;
- accepted playbook persistence;
- before/after repeat-ticket measurement;
- pilot ROI report.
