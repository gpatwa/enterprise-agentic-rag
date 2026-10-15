Status: AI persona advisory code review. Not the independent human review required by the plan.

# Independent code review (advisory): ADS-040 to ADS-079 and M7 hardening

Reviewed at `27663d6` on branch `claude/persona-reviews`. Scope: the analytics runtime (`app/runtime`), execution
(`app/execution`, `app/compiler/postgres.py`), review, rollout, evaluation gate, resilience backup, quotas, and
migrations 0004 to 0012. Evaluation harnesses under `reference_stack/` were read only to understand how the
runtime is wired. No code, tests, config, or manifest was changed.

How the findings were checked:

- Reading the code, with file:line citations below.
- Throwaway scripts under `/private/tmp/claude-501/persona-scratch/`:
  - `check_lease_pg.py` and `check_restore_pg.py` ran against a temporary local PostgreSQL 16 instance (Unix socket only, no
    network, removed afterwards), migrated with this repository's Alembic head.
  - `check_service_sqlite.py` ran against the local reference stack (SQLite control store, DuckDB lake).
- Existing tests for the touched areas still pass locally: ADS-009, 042, 045, 057, 066 and 068 (76 passed).

## Summary

The graph runner's compare-and-set commit (`transition_seq`, `from_node`, `from_status`, `lease_fencing_seq`) is
sound, and it is what keeps most races from corrupting run state. The SQL compiler and gateways are careful:
identifiers are quoted, values are bound, and the literals that get interpolated are typed enums or ints. Evidence
chaining, the append-only triggers, and the review separation-of-duties rules are well built.

The serious problems are in three places:

1. **PostgreSQL-only behaviour that the SQLite-only tests never exercise.** Lease expiry is compared as strings, so
   on PostgreSQL every live lease can be stolen. A restore leaves the outbox sequence behind the restored ids, so
   every transition commit then fails. Both were confirmed on a real PostgreSQL instance.
2. **Error mapping around lost races.** `StaleWorkerError` is not handled anywhere in the service, so a lost
   compare-and-set becomes an HTTP 500 and leaves the run stranded.
3. **Process-local state.** Result, explanation, validation-report and compiled-plan handoffs are never evicted.
   The rebuild hook is last-writer-wins. The quota counters are per process.

Run reads are authorized only by knowing the run ID. Rollout release pointers are not scoped to a tenant.

## Defects

Ranked by severity. "Confirmed" means a script or test in this review showed the failure. "No" means it was
established by reading the code.

| # | Severity | File:line | Issue | Failure scenario | Suggested fix | Confirmed by test/script |
|---|---|---|---|---|---|---|
| D1 | Critical (PostgreSQL) | `app/runtime/control_store.py:124` | `acquire_lease` decides whether a lease is live with `str(existing["expires_at"]) > _timestamp(current)`. On PostgreSQL the driver returns a `datetime`: `str()` gives `2026-10-15 22:54:59+00:00` (space, and the session's time zone offset), while `_timestamp` gives ISO `...T...+00:00`. A space sorts before `T`, so on the same date a live lease always looks expired. | Worker A holds a fresh lease. A client retries the same `Idempotency-Key`, and `analyze()` sees an `active` run and calls `_resume`. Worker B gets fencing 2 one second later. A's next commit fails (see D2, HTTP 500) and B re-runs A's node, executing the warehouse query twice. Mutual exclusion is gone for every run on PostgreSQL. | Compare `datetime` values: parse a string on SQLite, normalise both sides to aware UTC. Better, do the check in SQL (`WHERE expires_at <= :now`) in an `UPDATE ... RETURNING` or `INSERT ... ON CONFLICT DO UPDATE ... WHERE`. Add a PostgreSQL CI job for the control store. | Yes: `check_lease_pg.py` printed "worker 2 acquired a LIVE lease 1s later, fencing 2", both with the server time zone set to America/Los_Angeles and with `PGTZ=UTC`. |
| D2 | High | `app/runtime/analyze_service.py:118-123` and `:231-243`; `app/runtime/graph_runner.py:391` | `StaleWorkerError`, raised by `commit_transition` when the worker loses the CAS, is not caught in `analyze`, `_resume`, `clarify` or `decide_review`, and `api_v2.respond` only maps `ServiceError`. Separately, `analyze` catches **any** `IntegrityError` raised during the whole `start()` (outbox PK, lease-token uniqueness, transition idempotency key) as if it were the "duplicate create" race. | A lost race (D1, lease expiry under D4, or a cancellation requested while a node runs) returns HTTP 500 to the caller. The run is left `cancel_requested` or half-advanced. Nothing resumes a `cancel_requested` run: `analyze` only resumes `status == "active"`, and no code in `app/` calls `request_cancellation`. Every later poll reports `running` for ever. | Map `StaleWorkerError` and `LeaseUnavailable` to a 202 `running` response. Narrow the `IntegrityError` catch to `create_run` only (split `start` into create and execute). Let `analyze` and `_resume` drive `cancel_requested` runs to terminal. | Yes: `check_service_sqlite.py` [1]. A cancellation requested during `compile` gave HTTP 500, and the run row stayed `('cancel_requested', 'compile')`. |
| D3 | High (PostgreSQL) | `app/resilience/backup.py:156-166`; `alembic/versions/0002_agent_control_store.py:180` | Restore inserts explicit `analytics_run_outbox.id` values but never moves the `SERIAL` sequence on. | After a restore that the manifest verifies as good, the first new outbox inserts reuse ids 1..N. Every `commit_transition` fails with a PK violation, which D2 turns into a 500. The service is down until N failed attempts have used up the sequence, and N can be millions. The ADS-068 drill does not catch this because it runs on SQLite. | After the insert, run `SELECT setval(pg_get_serial_sequence(t, c), max(c))` for every identity or serial column; find them by reflection. Add a PostgreSQL restore-then-write test. | Yes: `check_restore_pg.py` gave `UniqueViolation ... analytics_run_outbox_pkey`. |
| D4 | High | `app/runtime/control_store.py:57,95`; `app/runtime/graph_runner.py:159-289` | Leases are 30 s and are **never renewed**: there is no heartbeat, and `renewed_at` is only written on acquire. One `execute` can take the full `ExecutionLimits.timeout_seconds` of 30 s, plus EXPLAIN, plus LLM calls. | Any run longer than about 30 s can be taken over by a retry with the same idempotency key, even on SQLite. Takeover re-executes the current node (duplicate warehouse cost), and the first worker hits D2. | Renew the lease before each node, and from a timer during long nodes, with a fencing-checked `UPDATE`. Keep the lease longer than the longest node budget. Check the remaining lease before starting a cost-bearing node. | No (reasoned; D1 shows the takeover mechanics) |
| D5 | High | `app/execution/bridge.py:22`, `app/runtime/explain_stage.py:18`, `app/runtime/evidence_sealer.py:22`, `app/runtime/governed_stages.py:32` | `ExecutionResultStore._results` (full result rows), `ExplanationStore`, `ValidationReportStore`, and `CompiledPlanStore._plans` are process-local dicts with no eviction. Only `PolicyValueStore` is bounded. | A long-running API process keeps every result row set for every run until it is restarted, so memory grows without limit (rows can be up to 5 MB per run under the default `max_bytes`). This also undercuts the "rows are never stored" statement, because the rows are kept, in memory, for ever. | Bound these stores (LRU or TTL keyed to terminal plus a grace period), or drop them when the run is sealed. Keep `answer_for` returning the documented "unavailable, resubmit" outcome. | No |
| D6 | Medium-High (conditional) | `app/execution/bridge.py:24,90-91` | `ExecutionResultStore.rebuilder` is a single attribute, overwritten by each `GatewayExecutor`. The runner factory builds a new executor per request (`reference_stack/stack.py:190`). | With per-tenant or per-data-plane gateways (ADS-064), tenant A's in-flight result rebuild (`results.resume`) can run A's stored SQL on whichever gateway the last request registered, which may be tenant B's warehouse. B's numbers would then be labelled as A's. It is also a data race across threads. | Pass the executor or gateways explicitly to `resume` (or key the rebuilders by tenant and dialect). Never use shared mutable state as a hook. | No |
| D7 | Medium | `app/runtime/analyze_service.py:150-152`, `:138-139` | `status()` checks only tenant and purpose. Any user in the tenant who knows a run ID gets the full answer, including rows computed under the **requester's** identity claims and policy values. Protection rests on the run ID being unguessable, and `run_id_key` defaults to `None` (derivable IDs). | User B, whose groups or claims would deny or row-filter the data, reads user A's result through `GET /runs/{id}`, the agent tools, or the artifact builder. The response even echoes B as `user_id`. | Bind run reads to the requester (the `_tag` check `clarify` already does), plus authorised reviewers of a paused run, or re-authorize the caller against the run's policy decision. Make `run_id_key` mandatory outside tests (fail closed). | Yes: `check_service_sqlite.py` [2]. Another user (`groups=contractor`) got HTTP 200 with the answer and 3 rows. |
| D8 | Medium | `alembic/versions/0011_rollouts.py:47-54`; `app/rollout/store.py:113-152`; `app/rollout/controller.py:175-195,227-236` | `analytics_release_pointer` is keyed by `prompt_name` only, with no `tenant_id`, while rollouts and registry candidates are tenant-scoped. `promote` does not check that the active version still equals `baseline_version`. `rollback` blindly appends `baseline_version`. | Tenant A promotes `intent@v3`. Tenant B's rollout of the same prompt name then fails with `stale_parent`, or B's rollback resets A's pointer. Within one tenant, two rollouts from the same parent both promote (the last one wins), and rolling back the older one silently reverts the newer promotion. | Add `tenant_id` to the pointer's PK and queries. In `promote` and `rollback`, compare-and-set on the current pointer `seq`/version and refuse when it has moved. | No |
| D9 | Medium | `app/resilience/backup.py:75-78,109-112` | Backup reads each table in its own connection or transaction, so the snapshot is not consistent. | A backup taken while runs are in flight captures transitions or checkpoints that don't match `analytics_agent_runs` (or the outbox). The restore either fails FK checks on PostgreSQL or restores runs whose projection and history disagree. `verify_backup_files` cannot detect this. | Dump every table in one `REPEATABLE READ READ ONLY` transaction (PostgreSQL: `SERIALIZABLE READ ONLY DEFERRABLE`; SQLite: one `BEGIN`). | No |
| D10 | Medium | `app/runtime/evidence_sealer.py:40-47`; `app/runtime/analyze_service.py:285-286` | Sealing happens lazily on the first `_respond`, using a process-local validation report. If the first read happens in a process without the report (a different replica, a restart, or `analyze` returning `running` after `LeaseUnavailable`), the envelope is sealed without validation and is immutable. Later, the original process's seal raises `EvidenceConflictError`, which is silently swallowed. | Evidence for some runs silently lacks the result-validation section, depending on which replica answered first. Feedback and replay then bind to weaker evidence. | Seal in the same step that commits the terminal transition (or persist the report durably and seal from it). Do not swallow `EvidenceConflictError`; log or alert on it. | No |
| D11 | Medium | `app/quotas/guard.py:52-61`; `app/quotas/manager.py:48-52` | Cost is attributed only if the **metered call itself** returns `terminal`. A run that finishes on another worker, or is observed through the unmetered `status()`, is never charged. Quota state is also per process. | The daily cost budget can be under-counted (a duplicate request that returns `running`, or a run that completes in the background). With N replicas the effective quota is N times the configured one. `_recorded` grows without limit. | Attribute cost when the terminal transition commits (an outbox consumer), not in the HTTP path. Keep quota counters in shared storage. Bound `_recorded` by day. | No |
| D12 | Medium | `app/runtime/governed_stages.py:37,40-46,100-108` | The compiled-plan reference is `sha256(tenant:run:sql)`, which does **not** include bound parameters. `_insert_once` keeps the first durable row and the in-memory copy keeps the last. The cost-review `plan_fingerprint` is this same reference, so the human approval does not bind to the parameter values. `_insert_once` is also SELECT-then-INSERT (a TOCTOU race that raises `IntegrityError`). | If a run recompiles the same SQL shape with different values (a resume after policy values change, or a future re-plan path), another process resumes with the stale durable parameters. A reviewer's approval covers "this SQL shape", not "these filters". | Hash the canonical `(sql, parameters, dialect)`. Use `INSERT ... ON CONFLICT DO NOTHING` and verify that the stored content matches. | No |
| D13 | Medium | `app/runtime/governed_stages.py:164-172`; migration `0012` | `PolicyValueStore.discard` is never called, and plans and result links are never deleted. `analytics_run_policy_values` keeps identity-claim filter values (sensitive) for ever. These tables have no FK to runs, and they are included in backups as plain-text JSON. | Identity claims accumulate without limit and are copied into every backup directory, against the docstring's "short-lived handoff". | Delete policy values, plans and links when a run goes terminal (in the same transaction) or through a TTL sweeper. Add an FK with cascade to `analytics_agent_runs`. | No |
| D14 | Low-Medium | `app/review/rules.py:24-38`; `app/review/service.py:67-96` | `decide` is check-then-append with no lock. `derive_state` returns `rejected` on any rejection event, even after the approval quorum had already been met. | A concurrent approve and reject (or a reject that lands just after approval) flips a review that a rollout or evaluation gate already acted on from `approved` to `rejected`. The same race can record an approval after expiry. | Stop the state at the first terminal decision: ignore events after quorum, rejection or expiry. Append under a lock on the review row, or with a "last seen seq" CAS. | No |
| D15 | Low-Medium | `app/runtime/graph_runner.py:209`; `app/runtime/evidence.py:108-116` | Run-level cost accounting reads `output.payload["cost_units"]`, which no production node emits. So `observed_cost_units` is always written as `0.0`, and the run budget is only checked against the estimate. | Evidence envelopes claim an observed cost of 0. The quota guard silently falls back to the estimate. The graph's cumulative cost budget never trips on real execution. | Have `execute` report the gateway's `estimated_cost_units`/elapsed time as `cost_units`, or remove the "observed" field until it is real. | No |
| D16 | Low-Medium | `app/execution/calibration.py:74` | A fitted calibration can have a large negative offset, and `max(0.0, ...)` then turns small estimates into 0. | An approved calibration silently makes queries cost 0, skipping the cost-approval threshold and the budget check. The human approving it may not see this in the numbers. | Reject fits whose intercept is below 0 (or clamp to the raw estimate's floor), and show the zero-cost region in the approval artefact. | No |
| D17 | Low | `app/runtime/control_store.py:126,230-246` | The fencing number comes from the lease row only, and `release_lease` deletes that row (on every review or clarification pause). The next acquire restarts at fencing 1. `run["lease_fencing_seq"]` is read but ignored. | Fencing tokens are not monotonic over a run's life. A zombie worker is currently stopped only by the `transition_seq` CAS, not by fencing. | Use `max(lease.fencing_seq, run.lease_fencing_seq) + 1`. | No |
| D18 | Low | `app/runtime/analyze_service.py:405-406` | `_owner()` is a hash of the wall-clock timestamp, and the same value is used as `lease_token`, which is UNIQUE across all runs. | Two requests in the same microsecond collide. The `IntegrityError` is then misread as a create race (D2), or becomes a 500 in `_resume`. | `secrets.token_hex(16)` for the token, and a stable worker ID for `owner_id`. | No |
| D19 | Low | `alembic/versions/0002_agent_control_store.py:16-59,160-187` | The outbox has no consumer anywhere in `app/`. Checkpoints store the full state, including the growing evidence tuple, per transition (O(n²) per run). Append-only triggers combined with `ON DELETE CASCADE` make deleting a run impossible. | The control store grows without limit, and there is no retention path at all. | Add an outbox relay, or drop the outbox until there is one. Design retention (partition and drop, or a privileged purge that disables the triggers), and store checkpoint deltas. | No |

Checked and found sound:

- The compiler's SQL composition: identifiers are quoted, values are bound, and granularity, direction and limit are
  typed enums or ints.
- The DuckDB sandbox: external access is disabled and the configuration is locked.
- The PostgreSQL gateway runs read-only, sets `statement_timeout`, maps cancel vs timeout correctly, and always
  rolls back.
- Evidence chain append retries on PK contention and verifies the chain.
- The review and rollout migrations' downgrades.
- `resolve_review`'s identity, fingerprint and expiry checks.

## Design risks (not bugs)

1. **SQLite is the only tested control-store dialect.** The reference stack and nearly all tests use SQLite with
   `PRAGMA foreign_keys` off (only ADS-009 turns it on). D1 and D3 show this hides real PostgreSQL defects. FK
   behaviour (evidence FK, restore order) is largely untested.
2. **Graph state stays durable, but the side effects of a node do not have the same guarantee.** Fencing protects
   the state commit, not the warehouse query, review creation, or policy-value write that happened before the commit
   lost. With D1 and D4 this means duplicate query cost and orphaned rows. Consider an execution ledger keyed by
   `(run, plan_reference)` and checked durably before execution; today the `has()` check is in memory only.
3. **Status reads have side effects.** They seal evidence, run `get_review ... FOR UPDATE`, and can expire reviews.
   That makes read latency and lock contention depend on poll rate.
4. **Authorization by run-ID secrecy** (D7), plus the insecure default `run_id_key=None`.
5. **Per-process quotas and SLO trackers** (D11). They cannot enforce a tenant quota across replicas.
6. **Approvals bind to fingerprints that do not cover everything a human would assume.** The cost review covers the
   SQL text only (D12). The policy review covers the intent, but is then turned into a `stale_context` failure on
   approval. That is intended, but a reviewer UI should say so.
7. **Cost units are uncalibrated** and differ per dialect (DuckDB uses cardinality, PostgreSQL uses planner cost),
   and the same `approval_threshold` applies to both.
8. **Intent echo (M7-H2) is lexical.** It can be satisfied by a question that contains the right words with a
   different meaning (for example "not by region"), and the ADS-073 measurement covers false abstention, not false
   acceptance.
9. **Backups contain identity-claim values** (D13) and are unencrypted JSON lines. The integrity digest is unkeyed,
   so anyone who can write the backup can recompute it. "Tamper-evident" holds only against accidental corruption.

## Test gaps

- No PostgreSQL run of `ControlStore` (lease, CAS, review FOR UPDATE paths), of migrations 0004-0012, or of
  backup/restore followed by new writes.
- No test that a live lease survives a duplicate `analyze()` with the same idempotency key while a node is running,
  or of lease expiry while a slow node runs (D1, D4).
- No service-level test for `StaleWorkerError` or `LeaseUnavailable` mapping, or for a cancellation requested
  mid-run (D2). `request_cancellation` has no caller or API.
- No test that a different user in the same tenant cannot read another user's run (D7). The ADS-074 isolation
  suite covers cross-tenant and wrong-purpose reads only. ADS-067 covers guessability only.
- No multi-process test: seal in process B without the report (D10), resume in process B with durable plans after
  process A recompiled, or rebuilder ownership (D6).
- No memory-bound test for the process-local stores (D5).
- No cross-tenant rollout test with the same prompt name, and no test of overlapping rollouts or a rollback after a
  newer promotion (D8).
- No concurrent approve/reject test for reviews (D14).
- No test that backup is consistent under concurrent writes (D9).
- No calibration test with a negative intercept (D16).
- Quota attribution is not tested for runs that end outside the metered call (D11).

## Suggested human review order

1. **ADS-009/ADS-030 control store and the ADS-045 analyze service** (`control_store.py`, `analyze_service.py`,
   `graph_runner.py`). Covers D1, D2, D4, D7, D17 and D18. This is the core correctness and isolation boundary, and
   D1 is release-blocking for any PostgreSQL deployment.
2. **ADS-068 resilience** (`backup.py`). Covers D3 and D9: a verified restore that then fails every write, and
   backups that are not consistent snapshots.
3. **M7 hardening (H1 durable run material) and ADS-040/ADS-075 execution bridge** (`governed_stages.py`,
   `bridge.py`, migration 0012). Covers D5, D6, D12 and D13.
4. **ADS-057 rollout and ADS-055 review.** Covers D8 and D14 (tenant scoping of the release pointer, decision
   races).
5. **ADS-050 evidence sealer and ADS-066 quotas.** Covers D10, D11 and D15 (evidence completeness and cost
   attribution).
6. **M7-H4 calibration (D16) and M7-H2 intent echo** (design risk 8). These are lower risk, but the calibration
   approval artefact should show the zero-cost region.
