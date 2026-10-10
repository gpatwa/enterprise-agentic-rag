# ADR-LLM-001: Resolution Intelligence Trust Boundaries

Status: Accepted for bounded, pre-production implementation
Date: 2026-08-23

## Context and Existing Baseline

Compass has a provider-neutral enterprise search contract. `SearchScope` is an
immutable tenant, principal, purpose, and ACL context; search requests are
bounded; results retain rank, retrieval-source, evidence, index-generation,
content, permission, and embedding versions. OpenSearch is the derived search
plane, while canonical records and actions remain authoritative elsewhere.

`SearchService` owns timeout, normalized provider errors, observable fallback,
and cancellation behavior. `SupportResolver` performs tenant-scoped support
retrieval, has a deterministic answer fallback and citation-label check, and
uses the provider-neutral `LLMClient`. Support actions are tenant-scoped,
start in `generated`, retain audit events, require explicit approval/status
progression, and use local mock execution. These are the baseline trust layers;
this ADR does not replace them.

This decision depends on OS-088 as recorded in the execution packet. It makes
no claim that the planned LLM pipeline is implemented or production-ready.

## Decision and Request Flow

Use an LLM as a bounded reasoning layer above authorized OpenSearch retrieval:

```text
ticket/question
  -> deterministic normalization and fast path
  -> typed intent and bounded search plan
  -> OpenSearch retrieval under immutable SearchScope
  -> deterministic fusion/pre-rank
  -> optional bounded LLM rerank of supplied candidates
  -> versioned evidence packet
  -> structured cited resolution and abstention decision
  -> typed action proposal
  -> deterministic policy and human approval
  -> existing action queue and execution/audit path
```

OpenSearch and `SearchScope` own retrieval and authorization. The LLM may
interpret, plan, rank supplied evidence, synthesize, and propose. It cannot add
candidates, modify scope, approve commands, execute tools, or become a system
of record.

## LLM Responsibilities

- Extract typed support intent, entities, constraints, and search rationale.
- Produce at most four bounded lexical/semantic query variants without changing
  `SearchScope` or dropping exact identifiers.
- Rerank only an authorized top-N candidate set, preserving candidate IDs and
  evidence versions.
- Synthesize a concise resolution containing structured claims, steps,
  customer response, citations, confidence, and abstention where appropriate.
- Propose an allowlisted, typed support command for deterministic policy review.

All output is untrusted input. Strict schemas reject malformed or extra fields;
unknown citations, unsupported claims, and unsupported action parameters cause
fallback or abstention.

## Deterministic Trust-Layer Responsibilities

- **Retrieval:** OpenSearch, immutable `SearchScope`, tenant/ACL filters,
  candidate bounds, query limits, provenance, and index/version ownership.
- **Reasoning boundary:** prompt construction treats retrieved text and ticket
  content as quoted data, and supplies only minimum required evidence fields.
- **Policy:** confidence thresholds, evidence sufficiency, abstention, command
  allowlists, risk, approval requirements, and kill switches.
- **Approval:** existing human approval/status transitions; the model cannot
  advance an action state.
- **Execution:** existing action queue, integration boundaries, mock/local
  execution, idempotency, and audit receipts.
- **Operations:** timeout, fallback, redacted telemetry, model/prompt/policy
  versions, token budgets, rollout controls, and audit-log exclusions.

## Model Routing, Budgets, Fallback, and Kill Switch

Use cost-aware routing: cheap/fast models for normalization, obvious intent,
and bounded planning; a stronger model only when the policy permits it for
reranking or synthesis. Exact thresholds, model identifiers, prompt versions,
token caps, and budget accounting are release configuration, not model output.
Every call has a timeout, input/output token cap, route, immutable prompt/model
version, redacted metrics, and deterministic fallback. Failure, timeout, budget
exhaustion, invalid JSON, or policy rejection degrades to deterministic search,
the existing fallback answer, or abstention. A configuration kill switch must
disable calls immediately without affecting the deterministic path.

## Alternatives

| Alternative | Decision | Rationale |
|---|---|---|
| LLM-only retrieval | Rejected | It cannot own authoritative tenant/ACL filtering or bounded retrieval. |
| Deterministic RAG only | Not selected | It preserves trust but does not provide typed intent, bounded planning, or synthesis quality needed for messy tickets. |
| One large model for every stage | Rejected | Cost, latency, blast radius, and uniform failure behavior are unnecessarily high. |
| Specialized small/large model routing | Selected | Matches task complexity and budget while keeping deterministic degradation. |

## Security, Privacy, and Tenant Isolation

Authorization occurs before every reranking or synthesis call. The model sees
only authorized, minimum-size evidence; cross-tenant candidates and scope
changes are rejected. Ticket, comment, and article text is data, never
instruction. Prompt boundaries, bounded lengths, control-character handling,
and adversarial tests address prompt injection. Raw tickets, prompts, model
responses, and embeddings are excluded from normal logs and metrics. Provider
SDK types remain behind `LLMClient` adapters. No live model call, external
action integration, cloud deployment, or automatic execution is part of this
ADR.

## Evaluation and Rollout Requirements

Before any production consideration, the execution plan must provide an
adversarial golden corpus and offline evidence for citation precision,
supported-claim rate, abstention accuracy, action validity, latency, token
cost, and ranking quality. Validate model-off and model-on paths with scripted
fakes, timeout/error cases, prompt injection, ACL conflicts, fabricated
citations, unsafe commands, and log redaction. Roll out behind feature flags
and shadow mode; require human review and explicit quality, cost, security,
and operations gates. This ADR records the architecture only, not those exit
results.

## Deferred Decisions

Learned ranking beyond the bounded optional reranker is deferred until the
golden corpus and deterministic baseline establish measurable benefit without
authorization or provenance regression. Multimodal input, image/document
vision, audio, and multimodal embeddings are deferred until a concrete support
use case, data-retention policy, evaluation set, and cost model exist.

## Conditions That Reopen the Decision

Reopen if authorization, scope ownership, approval, or execution would move to
the model; if deterministic fallback cannot preserve tenant isolation or
bounded behavior; if measured quality, latency, cost, privacy, or security
fails its release gate; if a required provider cannot fit behind `LLMClient`;
or if production requirements demand live external execution or multimodal
capabilities outside this record.

## References

- [LLM Search and Resolution Intelligence Execution Plan](../LLM_RESOLUTION_INTELLIGENCE_EXECUTION_PLAN.md)
- [OpenSearch Enterprise Search Plane ADR](ADR-OS-001-opensearch-enterprise-search.md)
- [LLM-001 execution packet](../execution/llm-resolution/LLM-001-architecture-adr.md)
