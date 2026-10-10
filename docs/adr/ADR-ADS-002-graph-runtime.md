# ADR-ADS-002: Bounded Internal Graph Runner Before Temporal

Status: Proposed for independent architecture review
Date: 2026-09-05
Decision scope: Enterprise Analytics graph execution runtime

## Context

The Agentic Data Stack needs to coordinate deterministic gates, model-assisted
steps, human approval, and read-only external tools. The graph must preserve
tenant and purpose scope, durable evidence, bounded work, and replayable state.
It must also support the local Docker reference environment and Azure staging
without making a production infrastructure commitment.

[ADR-ADS-001](ADR-ADS-001-agentic-data-stack-boundary.md) establishes the
enterprise analytics product as a separate deployable. It names PostgreSQL as
the authority for run state and evidence, makes the LLM an untrusted reasoning
component, and requires the first graph runner to be an internal typed state
machine. The execution plan further requires a fake two-node graph to be
created, checkpointed, resumed, and terminated before Milestone 0 exits.

The runtime therefore needs more than an in-process function chain, but the
first release does not yet require a general distributed workflow platform.

## Decision

Build a narrow internal typed runner first. It will execute a versioned graph
definition against a versioned `AgentRunState`, persist every accepted
transition and checkpoint in the analytics PostgreSQL control store, and use
short-lived leases for ownership. The runner is a product-domain state machine,
not an LLM framework, MCP server, or graph database.

The first runner supports the bounded analytics lifecycle:

```text
create -> bootstrap -> retrieve -> resolve -> plan -> validate
        -> compile -> policy -> estimate -> approve? -> execute
        -> result_validate -> explain -> terminal
```

Clarification, refusal, review, and failure are explicit terminal or pause
outcomes. Offline improvement is a separate workflow boundary and is not an
unbounded extension of a request-time run.

Temporal remains the preferred later platform candidate when measured workload
evidence crosses the migration trigger below. Introducing it now would add a
service, worker fleet, deployment lifecycle, operational skill requirement,
and a second durable workflow authority before those costs are justified.

## Runtime contract

The runner owns orchestration only. Node implementations own domain work within
their declared contracts.

| Runtime concern | First implementation | Required invariant |
|---|---|---|
| Graph definition | Immutable, versioned, allowlisted node and edge definitions | Unknown node, edge, or version fails closed |
| Run state | Versioned `AgentRunState` in PostgreSQL | State is serializable, tenant-scoped, and schema-validated |
| Transition | Atomic compare-and-set from current state/version | One accepted predecessor and one audit fact per transition |
| Checkpoint | State snapshot plus transition sequence | Resume starts from the last committed boundary |
| Ownership | Lease token, owner ID, expiry, and fencing sequence | Expired workers cannot commit newer state |
| Retry | Per-node typed retry policy and run budget | Only retryable failures are retried; attempts are observable |
| Side effects | Tool idempotency key and result reference | Replays do not duplicate an external effect |
| Cancellation | Durable cancel request checked at boundaries | Cancellation converges to `cancelled` or an explicit failure |
| Evidence | Immutable transition, decision, and result references | A terminal outcome has a complete trace or an explicit gap |

The runner must not accept raw model-generated SQL, arbitrary tool names, or
unvalidated state patches. A node can write only fields in its declared output
schema. Deterministic policy, compilation, and execution gates remain
authoritative even when a prior model-assisted node requested them.

## Failure handling

Failures are classified before any retry decision:

| Failure class | Examples | Runner behavior |
|---|---|---|
| Invalid input | Missing tenant, purpose, or required request field | Fail closed; no node execution |
| Contract violation | Bad state version, undeclared output, unknown transition | Fail closed and record the offending contract |
| Policy/security | ACL mismatch, uncertified semantic object, forbidden file/path | Refuse or review; never retry automatically |
| Ambiguity | Multiple metrics or grains remain plausible | Ask for clarification within the run budget |
| Stale dependency | Context snapshot or semantic version expired | Rebuild or request review according to policy |
| Transient dependency | Connection reset, bounded 5xx, rate limit | Retry only when the node policy allows it |
| Permanent dependency | Invalid SQL AST, unsupported dialect, missing table | Fail with evidence; do not retry unchanged input |
| Worker/process loss | Crash, timeout, host termination | Lease expires; another worker resumes from checkpoint |
| Cancellation | User or policy cancellation | Stop at the next safe boundary and finalize cancellation |
| Unknown | Unclassified exception or corrupted response | Fail closed, retain diagnostic reference, page operations |

No retry may bypass identity, semantic certification, policy, approval, or
result-validation gates. A retry must preserve the same run identity and use a
new attempt number. If a retry could repeat a side effect, the tool must first
prove idempotency or the runner must stop for review.

## Checkpoint and resume

The runner commits a checkpoint only after the node output has passed schema
validation and the transition has been appended to the audit log. The atomic
write includes the run ID, graph version, state version, transition sequence,
current node, serialized state, context snapshot reference, and evidence
references. The checkpoint is immutable by sequence; the current pointer is a
transactionally updated projection.

On resume, a worker:

1. Acquires a fresh lease using a fencing sequence.
2. Loads the latest committed checkpoint and verifies graph/state versions.
3. Replays or verifies the transition chain up to that checkpoint.
4. Re-evaluates cancellation, expiry, and run budgets.
5. Continues only from the declared current node.

An uncommitted node result is treated as unknown. The node is retried only when
its tool contract is idempotent or the prior attempt has a durable result
reference that can be safely adopted. The runner never guesses whether an
external query or mutation completed.

## Leases and fencing

Each active run has a lease with a bounded TTL, renewable only by its current
owner. A transition includes the lease fencing sequence. PostgreSQL rejects a
commit from an expired or superseded sequence, preventing a paused worker from
overwriting a resumed run. Lease acquisition is conditional on the run being
non-terminal and not held by a live owner.

The first implementation uses short leases sized to the node boundary, not to
the full run. Long-running external work must be represented by a typed
operation reference and polled under a new lease. A human approval pause does
not hold a worker lease.

## Retry, idempotency, and cancellation

The default request-time retry budget is one transient execution retry. Each
node declares timeout, retryable error classes, maximum attempts, and an
idempotency mode. The runner applies exponential backoff with a bounded
deadline and records the decision; it does not use an implicit global retry.

Idempotency keys are derived from the stable run ID, transition sequence, node
ID, and logical operation key. A tool adapter must either return the same
result for a repeated key or expose a durable operation status lookup. Read-only
queries still receive keys so duplicate evidence and billing can be detected.

Cancellation is a durable request with actor, time, reason, and policy source.
Nodes check it before starting work, before committing output, and before
waiting for another external poll. Cancellation cannot interrupt a database
operation mid-flight; the adapter must honor its timeout and then the runner
records the resulting terminal state. A cancellation race resolves by the
first committed terminal transition, with the losing request preserved in the
audit record.

## Observability and audit

Every run and transition emits structured telemetry with:

- tenant, purpose, run, graph, node, attempt, and correlation IDs;
- state and contract versions, transition sequence, and outcome;
- lease owner/fencing metadata without secrets;
- latency, queue wait, token usage, model/provider, retry, and cost estimates;
- context snapshot, semantic contract, policy, compiled-plan, and result
  fingerprints;
- error class, redacted diagnostic reference, and cancellation reason.

Metrics cover active runs, terminal outcomes, checkpoint age, lease expiry,
resume count, retry rate, cycle detection, node latency, stuck runs, and
evidence completeness. Traces must show the authored graph path, including
clarification, refusal, review, retry, cancellation, and failure branches.
Sensitive customer rows and secrets are excluded from logs by construction.

Operational alerts are based on bounded conditions: expired leases, runs past
their deadline, repeated resume failures, outbox lag, missing terminal
evidence, and unexpected transition rejection. Logs and traces are diagnostic;
the PostgreSQL audit facts remain the source of truth for authorization and
replay.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| In-process function chain | Reject | No durable resume, ownership, or complete transition audit |
| Internal typed runner with PostgreSQL | Select first | Fits bounded request/review lifecycle and existing authority boundary |
| LangGraph or similar agent framework | Reject as runtime authority | Useful orchestration patterns may be studied, but policy and state contracts must remain Compass-owned |
| Temporal now | Defer | Strong durable execution, but operational and deployment cost is premature for the current bounded workload |
| Graph database plus workflow engine | Reject for first release | Adds two authorities without evidence that bounded in-memory context closure is insufficient |
| Managed cloud workflow service | Defer | Couples local reference behavior and correctness to a cloud before staging evidence exists |

Temporal is not ruled out. Its durable timers, activity heartbeats, workflow
history, worker routing, and operational tooling become valuable when the
workload contains long-running asynchronous workflows or recovery demands that
the internal runner cannot meet without recreating those capabilities.

## Migration trigger to Temporal

Re-open this ADR after two consecutive staging evaluation windows, using the
same pinned scenario corpus and trace definitions, if any of the following are
true:

- p95 active-run duration exceeds 15 minutes for supported workflows, or more
  than 10% of runs require a durable wait longer than five minutes;
- worker-loss or lease-recovery tests cannot meet a 99.9% resume-within-SLO
  target without manual repair;
- the internal runner requires more than two independently deployed worker
  pools or more than 100 concurrent active runs in the supported staging
  profile;
- checkpoint, lease, outbox, or retry operations consume more than 20% of
  analytics control-store write capacity;
- operators perform manual recovery on more than 1% of runs in two consecutive
  windows;
- a required workflow capability, such as durable timers or multi-day human
  approval, cannot be implemented without weakening the typed contracts or
  audit guarantees.

The migration decision requires a measured comparison of correctness,
recovery, latency, operational burden, cost, and local/staging reproducibility.
It must preserve the `AgentRunState`, node I/O, transition, outcome, evidence,
idempotency, and cancellation contracts. Temporal is a replacement for the
orchestration implementation, not a replacement for Compass policy or audit
authority.

## Explicit non-goals

- Implementing the runner, schema, migrations, or worker process in this ADR.
- Introducing Temporal, a graph database, LangGraph, or an MCP runtime.
- Supporting arbitrary user-defined graph code or unrestricted loops.
- Allowing an LLM to approve, authorize, compile raw SQL, or execute tools.
- Guaranteeing exactly-once execution of an external system; the contract is
  at-least-once delivery with idempotent adapters and durable evidence.
- Holding worker leases through human approval or multi-minute external waits.
- Persisting customer result rows or secrets in graph state by default.
- Changing public V1 query behavior or adding compatibility behavior for
  nonexistent external customers.

## Consequences

The internal runner keeps the first release understandable, locally testable,
and aligned with the existing PostgreSQL authority. It makes failure and
recovery behavior explicit before scale claims are made. The cost is that
Compass must implement and test durable state, leases, outbox delivery,
idempotency, and operational repair itself.

The decision creates a clean future seam: a Temporal adapter may replace the
runner behind the same typed contracts once the trigger is met. Until then,
adding Temporal would increase operational surface without improving the
supported request path enough to justify it.

## Review questions

1. Are the internal runner's state, lease, checkpoint, retry, cancellation, and
   evidence invariants sufficient for ADS-003 through ADS-006?
2. Are the Temporal triggers measurable in local/staging evaluation rather than
   driven by anticipated scale?
3. Does the design preserve the ADS-001 authority and product boundaries?
4. Are at-least-once tool delivery and idempotent adapter responsibilities
   explicit enough for security and operations review?
