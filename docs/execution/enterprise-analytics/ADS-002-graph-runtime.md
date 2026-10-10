# ADS-002: Graph Runtime ADR and Migration Trigger

Status: Review
Milestone: M0, Program and graph foundations
Owner: Analytics platform and operations

## Objective

Choose and bound the first graph-runtime implementation for the Agentic Data
Stack. Define how a typed run survives worker loss, retries transient work,
prevents duplicate effects, handles cancellation, and produces an auditable
trace. Record the evidence threshold for a future Temporal migration without
introducing runtime changes in this packet.

## Dependencies

- [ADS-001 architecture boundary](ADS-001-architecture-boundary.md)
- [ADR-ADS-001](../../adr/ADR-ADS-001-agentic-data-stack-boundary.md)
- [Agentic Data Stack Execution Plan](../../AGENTIC_DATA_STACK_EXECUTION_PLAN.md)
- Existing analytics PostgreSQL control-store direction and read-only trust
  boundary

## Deliverables

- [ADR-ADS-002](../../adr/ADR-ADS-002-graph-runtime.md)
- Decision matrix covering internal typed runner, Temporal, framework-led
  orchestration, and managed workflow alternatives
- Failure taxonomy and operational invariants for later implementation packets
- Measurable Temporal migration trigger and contract-preserving migration rule

## Decision summary

Use a Compass-owned internal typed runner first. The runner will persist
versioned state and transition checkpoints in PostgreSQL, use fenced leases,
apply typed per-node retry rules, and expose durable cancellation and
observability. The first graph is bounded and allowlisted; it has no open-ended
reason-act loop.

Temporal is deferred until staging evidence shows that long waits, worker
recovery, concurrency, control-store pressure, manual recovery, or durable
timer requirements exceed the internal runner's tested envelope. A future
Temporal implementation must preserve the typed graph, state, evidence,
idempotency, and cancellation contracts.

## Required invariants for ADS-003 through ADS-006

1. A run is tenant- and purpose-scoped before it enters the graph.
2. Every accepted transition has one monotonic sequence and one audit fact.
3. Every checkpoint has a graph version, state version, current node, and
   evidence references.
4. An expired lease cannot commit after a resumed worker acquires a newer
   fencing sequence.
5. Only declared node outputs can mutate state.
6. Retries are typed, bounded, and visible in the trace.
7. External operations use stable idempotency keys or stop for review.
8. Cancellation is durable and converges at safe node boundaries.
9. Terminal outcomes are answer, clarify, refuse, review, fail, or cancelled;
   there is no implicit success or silent drop.
10. Logs and traces exclude secrets and customer rows; PostgreSQL audit facts
    preserve replayable evidence references.

## Failure and recovery scenarios

The implementation packets must add a scenario for each row and assert the
terminal outcome, transition path, checkpoint state, and evidence behavior.

| Scenario | Expected behavior |
|---|---|
| Process dies after node work but before checkpoint | Resume from prior checkpoint; retry only under the node's idempotency rule |
| Process dies after checkpoint but before response | Resume from current node and return the committed terminal outcome |
| Lease expires while old worker is paused | New worker fences the old owner; stale commit is rejected |
| Duplicate delivery of an external operation | Same idempotency key returns/adopts one durable result |
| Transient read-only dependency failure | One bounded retry with backoff, then explicit failure |
| Policy or ACL denial | Refusal or review; no retry or context broadening |
| Ambiguous metric or grain | Clarification within the allowed turn budget |
| Cancel request races with node completion | First committed terminal transition wins; cancellation is audited |
| Unknown exception | Fail closed with redacted diagnostic reference and alert signal |
| Corrupt or unsupported state version | Refuse resume and require reviewed migration/repair |

## Acceptance criteria

- ADR-ADS-002 is present and marked `Proposed for independent architecture
  review`.
- This packet remains `Review`; no author or delegated model marks it approved.
- Internal typed runner is selected for the first release and Temporal is
  explicitly deferred.
- Failure modes cover contract, policy, ambiguity, transient/permanent
  dependency, worker loss, cancellation, and unknown errors.
- Checkpoint/resume, leases/fencing, retries, idempotency, cancellation, and
  observability responsibilities are explicit.
- The Temporal migration trigger includes measurable thresholds and requires a
  staged evidence comparison.
- Non-goals include runtime implementation, migrations, public APIs, graph
  database adoption, unrestricted loops, and direct LLM authority.
- No runtime code, public API, database migration, provider dependency,
  generated artifact, or shared program manifest is changed by this packet.

## Validation

Run from the ADS-002 worktree:

```bash
git diff --check
```

Also run the repository's available documentation checks, if configured. Since
this packet changes only Markdown under `docs/`, runtime test suites and
database checks are intentionally out of scope. Before merge, an independent
architecture reviewer should answer the ADR review questions and leave the
packet in `Review` until that decision is recorded separately.

## Ownership and merge gate

This branch owns only:

- `docs/adr/ADR-ADS-002-graph-runtime.md`
- `docs/execution/enterprise-analytics/ADS-002-graph-runtime.md`

Merge only after ADS-001 is accepted by an independent reviewer and the
reviewer confirms that ADS-003 can implement the state/transition contract and
ADS-005 can implement the PostgreSQL checkpoint/lease/audit contract without
changing the decision. Do not update the shared ADS manifest in this packet.

## Residual risks

- The thresholds are initial staging hypotheses and need calibration against
  the ADS-007 baseline and later live adapter evidence.
- PostgreSQL checkpoint and lease correctness is specified here but not yet
  implemented or crash-tested; that is the responsibility of ADS-005.
- At-least-once delivery can still expose adapter bugs if a future tool ignores
  its idempotency contract.
- A later Temporal migration may introduce history, deployment, and replay
  compatibility work even if the typed contracts remain stable.
- Human approval and multi-day workflows may force an earlier re-review if
  product scope expands beyond the bounded first release.
