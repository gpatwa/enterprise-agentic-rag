# ADS-009 Independent Review and Remediation Plan

Status: **Technical remediation complete; M0 approval pending**
Reviewed commit: `b9868b5`
Judge: GPT-5.6 Sol, high reasoning effort
Review type: independent engineering and security assessment
Date: 2026-09-06

## Decision summary

The independent judge originally recommended **NOT READY**. Local remediation
now addresses M0-01 through M0-04 with composite identity constraints, a
transactional control-store adapter, signed routing authorization, and
purpose-scoped tool admission. The M0 gate remains open because live
PostgreSQL evidence and the required independent human approvals are still
outstanding.

This document is an engineering aid, not a security approval. Only the
authorized engineering and security reviewers may close the actions below and
record the M0 go/no-go decision.

## Findings and required actions

| ID | Severity | Finding | Required action | Acceptance evidence | M0 impact |
|---|---|---|---|---|---|
| M0-01 | Critical | Child control-store rows could carry a tenant ID that differs from the parent run; purpose was not consistently carried. | **Resolved locally.** Composite foreign keys now bind run, tenant, and purpose for checkpoints, leases, transitions, and outbox rows; tool purpose scope is enforced. | ADS-009 identity/scope test passes; live PostgreSQL confirmation pending. | Review evidence |
| M0-02 | High | The fake graph did not reload a checkpoint after worker loss or persist a terminal outcome. | **Resolved locally.** `ControlStore` reloads the latest checkpoint, rejects stale worker commits, writes transition/checkpoint/outbox/projection atomically, and validates terminal state after reopen. | ADS-009 recovery test passes; live PostgreSQL confirmation pending. | Review evidence |
| M0-03 | High | Runtime statuses and PostgreSQL statuses diverged; checkpoint history was mutable; expiry-aware acquisition and atomic CAS were not proven. | **Resolved locally.** Schema statuses match the runtime contract, leases take over only after expiry, checkpoints are append-only, and CAS checks identity, node, status, sequence, and fencing. | Migration and ADS-009 harness tests pass; live PostgreSQL drill pending. | Review evidence |
| M0-04 | High | Governed routing trusted caller-provided evidence and registry admission used a narrow denylist. | **Resolved locally.** Governed routing requires a short-lived HMAC authorization artifact; tool capabilities use an allowlist and enforce tenant/purpose scope. | Routing and registry adversarial tests pass. | Review evidence |
| M0-05 | High | Engineering review, security sign-off, and authorized go/no-go are not recorded. | Obtain independent architecture/engineering review, security disposition of residual risks, and the authorized owner’s M0 decision. Update the gate and threat-model sign-off fields with identity, date, decision, and evidence links. | Completed reviewer fields, decision record, and all blocking actions closed or explicitly accepted by the security owner. | Blocking |

## Accepted only with explicit sign-off

These items may remain deferred only if the security reviewer explicitly accepts
them in the M0 decision record:

- Production RLS and deployment-topology hardening beyond the local reference
  PostgreSQL drill.
- Distributed crash testing beyond the deterministic local recovery harness.
- Production graph-runner/API wiring and provider adapters reserved for later
  milestones.
- Adapter-level idempotent delivery beyond control-store enqueue deduplication.

An accepted residual risk must name the owner, affected boundary, mitigation,
expiry/review date, and follow-up milestone. Silence does not count as
acceptance.

## Evidence snapshot

- ADS-009 focused harness: `2 passed`.
- ADS-005 migration and contract remediation suite: `35 passed`, including recovery, fencing, identity, routing, and tool-scope assertions.
- Analytics service suite: `166 passed`.
- Ruff checks and `git diff --check` pass.
- The PostgreSQL drill script has been updated for the remediation, but Docker
  was unavailable on 2026-09-15, so live PostgreSQL evidence is pending.
- The current M0 gate remains in `Review`; no security approval is implied.

## Review record

Engineering reviewer: ____________________  Date: __________  Decision: __________

Security reviewer: _______________________  Date: __________  Decision: __________

Authorized M0 owner: _____________________  Date: __________  Decision: __________

Remediation tracking issue/packet: ______________________________
