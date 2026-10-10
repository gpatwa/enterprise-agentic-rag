# ADR-ADS-001: Agentic Data Stack Product Boundary

Status: Proposed for independent architecture review
Date: 2026-09-04

## Context

Compass has multiple product paths: support-resolution search, immersive
discovery, and the separately deployable enterprise analytics product. The
analytics product is evolving from a guarded text-to-SQL service into an agentic
operating path that can interpret a question, retrieve governed context,
compile a typed intent, execute read-only work, and preserve evidence.

The product has no external customer compatibility obligation yet. It does,
however, need stable internal boundaries so future model, storage, and cloud
choices do not make authorization, semantic certification, or audit behavior
ambiguous.

## Decision

Treat enterprise analytics as a separate product and deployable from the
support API. It may share platform contracts and infrastructure primitives, but
it owns its own API, agent graph, semantic registry, execution adapters,
evaluation suites, and evidence lifecycle.

The target flow is:

```text
caller
  -> analytics API and identity context
  -> bounded agent graph
  -> OpenSearch context retrieval
  -> certified semantic contract and typed analytical intent
  -> deterministic compiler and policy/cost gate
  -> read-only PostgreSQL or DuckDB adapter
  -> result validation and evidence record
  -> answer, clarification, refusal, review, or failure
```

The LLM is an untrusted reasoning component. It may extract intent, select
among supplied context, explain results, and propose changes for review. It may
not create executable SQL outside the compiler, broaden tenant or ACL scope,
certify semantics, approve an action, or write to a customer data source.

## Authority boundaries

| Concern | Authority | Boundary |
|---|---|---|
| Physical customer schema and rows | Customer PostgreSQL or approved warehouse | Read-only execution; never copied into the control store by default |
| Local and approved lake-file analysis | DuckDB adapter | Ephemeral, allowlisted, read-only views over approved files |
| Lexical/vector context retrieval | OpenSearch | Rebuildable derived index with tenant, ACL, generation, and certification filters |
| Business meaning | Git-backed Compass semantic registry | Versioned, certified contracts; no raw SQL in the contract |
| Metadata and lineage context | dbt, OpenMetadata, and physical providers | Normalized into immutable context snapshots |
| Run state and evidence | Analytics control store in PostgreSQL | Checkpoints, leases, transitions, outbox, evidence, and audit facts |
| Authorization and purpose | API identity and deterministic policy gates | Fail closed before retrieval, compile, and execution |
| Product behavior | Analytics service and graph runner | Separate deployable; no support API runtime dependency |

## Deployment boundary

Local Docker is the reference development and evaluation environment. Azure may
host staging infrastructure for runtime and operational evidence. This ADR does
not authorize Azure production deployment, public customer onboarding, or an
external managed OpenSearch commitment.

The current support-search path remains independently deployable. OpenSearch is
the target enterprise search plane there; Qdrant remains a legacy/local adapter
until its separate retirement decision is supported by measured evidence.

## Explicit non-goals

- A generic autonomous data engineer or unrestricted tool-using agent.
- Automatic writes, schema changes, dbt changes, or customer pipeline changes.
- A graph database as a first-release system of record.
- Replacing PostgreSQL or a customer warehouse with DuckDB.
- Treating OpenSearch as canonical business data or semantic authority.
- Coupling product correctness to a specific LLM, MCP implementation, or cloud.
- Claiming production relevance from synthetic fixtures or local benchmark lift.
- Adding backward compatibility layers for nonexistent external customers.

## Consequences

The analytics product can evolve its graph runner, semantic layer, retrieval
index, and execution adapters independently while preserving shared identity,
policy, and evidence contracts. The cost is an explicit integration boundary
and a requirement to keep versioned platform contracts synchronized.

The first graph runner is an internal typed state machine with durable
PostgreSQL checkpoints. Temporal remains a future option only when multi-hour
workflow evidence, worker recovery, or operational scale demonstrates that the
internal runner is insufficient.

The current architecture and request diagrams are generated from the versioned
Archify sources in `docs/diagrams/`.

## Review questions

1. Does the boundary keep support search and analytics independently deployable?
2. Are authority and fail-closed responsibilities explicit enough for security
   review?
3. Are the local and Azure-staging limits clear?
4. Is a future Temporal or managed-search decision based on evidence rather than
   premature infrastructure commitment?
