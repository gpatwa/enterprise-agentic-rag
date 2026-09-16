# ADS-009 M0 Integration Threat Model

Status: **Review: technical controls remediated; security sign-off pending**
Security reviewer: ____________________  Date: __________  Decision: __________
Engineering reviewer: __________________  Date: __________  Decision: __________

This threat model covers the deterministic local M0 composition harness only.
Human and security approval are still pending; this document is not an
approval or a production-readiness claim.

## Trust boundaries and assets

| Boundary | Assets and authority | Required control |
|---|---|---|
| Caller to run state | tenant, purpose, request and graph identity | typed state validation; tenant/purpose carried on every fact |
| Worker to control store | checkpoints, leases, transition evidence | conditional fencing and append-only transition facts |
| Graph node to tool registry | tool identity, contracts, scope, retry/idempotency metadata | exact lookup; registry has metadata only and no executor |
| Route selection to governed action | rollout, approval and audit context | explicit enablement; disabled/legacy/shadow fail closed |
| Test harness to fake graph | synthetic state and evidence | test-only fake nodes; no provider, API, cloud, or customer rows |

Assets include run identity, immutable transition evidence, checkpoint history,
lease fencing sequence, outbox dedupe key, routing approval context, and
redacted diagnostics. Secrets, raw SQL, customer rows, and executable tool
handles are explicitly outside the harness.

## Attacker assumptions and abuse cases

Assume a malicious or faulty model/node can forge payload fields, request an
unknown tool, broaden tenant or purpose scope, replay an outbox event, submit
a stale worker write, or attempt to enable governed routing. Assume a worker
can crash after work and before checkpoint, and that an operator can receive
duplicate delivery. The harness tests these cases:

- stale fencing is rejected after a resumed worker owns a newer sequence;
- duplicate outbox delivery has one dedupe record;
- cross-tenant/purpose use is rejected by composite foreign keys and declared scope boundaries;
- governed routing requires a short-lived signed authorization artifact;
- disabled and implicit governed routes refuse action;
- raw SQL and tool-execution capabilities cannot be registered;
- a registry result exposes metadata, not an executable handle.

## Mitigations and residual risks

Typed Pydantic contracts reject unknown fields and malformed state, transitions
are authored and evidence-bearing, the durable `ControlStore` makes
projection, transition, checkpoint, and outbox writes atomic, and the
route/registry contracts fail closed. SQLite migration tests exercise the same
composite constraints and append-only facts intended for PostgreSQL. The fake
graph uses deterministic synthetic identifiers and does not execute tools or SQL.

Residual risks remain: the updated local PostgreSQL drill has not run because
Docker was unavailable; production topology and RLS are out of scope; the
harness is not a distributed crash drill; adapter idempotency beyond the
control-store dedupe contract requires live integration evidence; and no
security reviewer has signed off. These risks block a security approval and
must remain visible at the M0 go/no-go review.
