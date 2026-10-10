# ADS-009: M0 Integration Gate

Status: **GO: approved**
Milestone: M0
Dependencies: ADS-003 agent-run-state contracts, ADS-004 typed tool registry,
ADS-005 PostgreSQL control-store schema, ADS-006 routing flags, ADS-007
baseline evidence, and ADS-008 compatibility boundary.

## Scope

The dedicated local test harness composes the existing state, transition,
routing, registry, and control-store contracts. It drives a deterministic fake
two-node graph through create, checkpoint, worker-loss/resume, and terminal
evidence. It also checks stale fencing rejection, outbox deduplication,
tenant/purpose scope, signed governed authorization, and absence of raw SQL/tool
execution authority. The harness uses the transactional `ControlStore`
boundary exercised by the local analytics service tests.

The fake graph is test-only. This packet does not add a production graph
runner, API wiring, providers, cloud deployment, or ADS-030 functionality.

## Acceptance evidence and commands

```bash
(cd services/analytics-api && PYTHONPATH=.:../.. pytest -q tests/test_ads009_m0_integration.py)
(cd services/analytics-api && PYTHONPATH=.:../.. pytest -q)
ruff check services/analytics-api/tests/test_ads009_m0_integration.py
ruff format --check services/analytics-api/tests/test_ads009_m0_integration.py
ADS009_DATABASE_URL=postgresql://<local-user>:<local-password>@127.0.0.1:5432/<disposable-db> \\
  python3 scripts/analytics/ads009_postgres_drill.py
git diff --check
```

The full analytics suite and focused checks are evidence for review, not a
security approval. ADS-007 and ADS-008 remain compatibility/baseline inputs;
this packet does not reproduce or alter them.

## Live local PostgreSQL evidence

On 2026-09-15, the updated live drill passed against a disposable PostgreSQL
15 database after Docker was restarted. The shared local `rag_db` was not used.
Current result:

```text
fencing_cas=pass
append_only_transition=pass
immutable_checkpoint=pass
tenant_purpose_fk=pass
terminal_replay=pass
outbox_dedupe=pass
skip_locked_contention=pass
```

Previously, on 2026-09-06, PostgreSQL 15.0 was started from the local Docker Compose
`postgres:15-alpine` service. Alembic upgraded a disposable database through
`0002_agent_control_store`, and `scripts/analytics/ads009_postgres_drill.py`
passed the following checks:

```text
fencing_cas=pass
append_only_transition=pass
outbox_dedupe=pass
skip_locked_contention=pass
```

The prior result predates the remediation schema and is retained only as
historical context. This is local PostgreSQL evidence only; it does
not substitute for production topology, authorization/RLS, or security sign-off.

## Independent review

The findings-first judge report and remediation actions are recorded in
[ADS-009 independent review](../../reviews/ADS-009-independent-review-2026-09-06.md).
Its current decision is **technical remediation complete**. Engineering,
security, and authorized-owner approval was explicitly granted in the Codex
task on 2026-09-15. Reviewer names were not supplied, so the record preserves
that provenance without inventing identities.

## M0 go/no-go checklist

- [x] Create, checkpoint, worker-loss resume, and terminal path is deterministic.
- [x] Every accepted fake transition carries evidence and a monotonic sequence.
- [x] Stale fencing, duplicate outbox delivery, scope, routing, and registry
  boundaries have negative assertions.
- [x] No production graph runtime, API, provider, cloud, manifest, or ADS-030
  change is included.
- [x] Updated local PostgreSQL concurrency/locking drill completed with the
  remediation schema, expiry takeover, fenced CAS, immutable checkpoints,
  tenant/purpose foreign keys, outbox dedupe, and `SKIP LOCKED` contention.
- [x] Independent engineering review completed on 2026-09-15; approval
  recorded from the owner instruction in the Codex task.
- [x] Human/security reviewer approval recorded on 2026-09-15 from the owner
  instruction in the Codex task; see the threat model record.
- [x] M0 go decision recorded by the authorized owner on 2026-09-15:
  **GO**, captured from the owner instruction in the Codex task.

M0 is **GO and approved** for the next milestone. The approval record does not
claim production deployment readiness beyond the documented local scope.
