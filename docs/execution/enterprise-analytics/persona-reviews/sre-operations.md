Status: AI persona advisory review (SRE / operations lead). Not an approval, sign-off, or human game day.

Reviewer: AI persona acting as an SRE / operations lead, 2026-10-15, branch `claude/persona-reviews` (base `27663d6`).
Scope: the five proposed policy/threshold files, the 11 `ops-*` and 6 `drift-*` runbooks, ADS-058/065/066/068/069/075 and M7-hardening
docs and reports, and the code under `app/quotas`, `app/resilience`, `app/operations`, `app/observability`, `app/drift`,
`app/runtime/governed_stages.py`, `app/execution/bridge.py`. Nothing was changed except this file. Local verification only: the six packet
test files pass (`104 passed`), plus two small read-only probes of `QuotaManager`/`SloTracker` behaviour (results below). No network,
no deploy, no live database or model.

## Summary

The mechanisms are solid for local work. Admission happens before execution, tenants are isolated, restores are verified, leases use
fencing, telemetry carries no content, and every alert names a runbook. **None of it is wired into the served process.** `app/main.py`
builds `V2Runtime()` with `service=None`, so the governed `/api/v2/analytics` path returns 503 `governed_runtime_not_configured`. No
code path mounts `QuotaGuardedService`, the observability wrappers, the dashboard, or the drift monitors, and nothing reads the proposed
policy files at runtime. As a result, approving the thresholds today would change no deployed behaviour, and an on-call engineer has no
way to see any of the signals the runbooks refer to.

These are the main operational findings beyond what the packets already list:

1. **Leases are never renewed.** `acquire_lease` is called once per start or resume, and nothing renews it. The lease is 30 s, and the
   gateway's default query timeout is also 30 s, before any LLM latency is added. With a real model and warehouse, a run will often
   outlive its lease. A client retry with the same key, or a clarify or review call, can then take over a run that is still alive.
   Fencing stops the stale worker from committing, but it does not stop a duplicate warehouse query or duplicate LLM spend. The
   `ExecutionResultStore.has` guard is per process.
2. **There is no takeover without a client.** A run only resumes when a caller re-submits analyze or calls clarify or review. No
   background sweeper exists, so "takeover within 2x lease" is not an objective the system actually enforces.
3. **Alert behaviour would be wrong for paging.**
   - `rate_limited` and `concurrency_limited` are deduplicated for the life of the process, not per day. The probe showed one alert
     across three simulated days.
   - `SloTracker.evaluate` has no deduplication, so every call raises the same alerts again (probe: 3 calls produced 6 alerts).
   - Both alert lists grow without bound.
4. **Cost units do not fit a real warehouse.** The PostgreSQL planner cost for one scan of a modest real table can exceed the whole
   proposed daily budget of 10,000 units. Model and token spend is not budgeted at all.
5. **Memory grows without bound.** The in-process maps in `ExecutionResultStore` and `CompiledPlanStore` are never evicted. Result rows
   (up to 5 MB each under the default limits) stay in API memory until the process restarts. `PolicyValueStore.discard` exists but
   nothing calls it, so durable policy values are never purged.
6. **Logical backups are not consistent snapshots.** Each table is read on its own connection, and the backup files are plaintext JSON
   that include request text and identity claims. Azure PostgreSQL Flexible Server PITR (7-day retention in `infra/terraform/azure/postgres.tf`)
   has to be the real backup, but no runbook describes it.
7. **Several runbooks describe things that do not exist or are out of date:**
   - a `Retry-After` hint (the guard drops `retry_after_seconds` and returns only a code);
   - "diagnose by run reference" (`diagnose_run` needs the raw run ID, and telemetry carries only `run_ref`, with no way to look it up);
   - "paused reviews fail closed after restore" (superseded by M7-H1);
   - a dashboard that is not served.

Ops view: **no-go for a pilot on the current code.** It becomes a conditional go once the wiring, lease, alert, and retention items in
"Pilot view" are done. None of these are large.

## Policy and threshold recommendations

All values below are **advisory proposals for the human owner**. None was applied.

| File | Recommendation | Exact amended values | Reasoning |
|---|---|---|---|
| `quotas/quota-policy.proposed.json`: `default` | **Amend** | `requests_per_minute: 20`, `burst: 10`, `max_concurrent_runs: 3`, `daily_cost_units: 2000000` (**provisional**; replace with the M7-H4 calibrated value after week 1), `warn_fraction: 0.5` | Pilot callers are people typing questions, plus clarify and review calls. 20/min per tenant is plenty, and a lower burst limits retry storms against a paid LLM. Per-tenant concurrency 3 times a few tenants keeps warehouse sessions single-digit (there is **no global cap**, see Deployment readiness). 10,000 PostgreSQL planner units is roughly one scan of an ~80 MB table, so it would lock tenants out on day 1. 2,000,000 is two maximum-cost queries (`ExecutionLimits.max_cost_units = 1,000,000`), which makes it a backstop rather than a budget. The real cost control for the pilot is the warehouse role (statement timeout, resource limits) plus an LLM provider spend cap. A 0.5 warning fraction gives an early signal while units are uncalibrated. |
| same: `tenants` | **Amend** | One explicit entry per pilot tenant, copying the default above | This makes per-tenant changes explicit, reviewable diffs instead of edits to the default. |
| same: `slo` | **Amend** | `success_target: 0.98`, `p95_latency_seconds: 30`, `fast_window_seconds: 3600`, `slow_window_seconds: 21600`, `fast_burn_rate: 14.4`, `slow_burn_rate: 6.0`, `min_requests: 10` | A real request makes two or more LLM calls (intent, explanation) at several seconds each, plus a warehouse query with a 30 s timeout, so an 8 s p95 would alert permanently. 0.98 allows for model-provider error rates during a pilot. Re-baseline both after 2 weeks of real data. With a few tenants, 20 requests in 5 minutes per tenant almost never happens, so the fast-burn page would never fire. 1 h and 6 h windows (the standard multi-window pairing) with a minimum of 10 make the alerts able to fire. Also, the SLO measures **HTTP call** latency, not end-to-end run latency including review; the owner should confirm that is what they want. |
| `resilience/objectives.proposed.json` | **Amend** | `rpo_seconds: 300`, `rto_seconds: 14400`, `lease_seconds: 120`, `takeover_factor: 1.5` | RPO 5 minutes is what Azure PostgreSQL Flexible Server PITR provides, so promise that, not the logical backup cadence. RTO 15 minutes is not credible without 24x7 on-call, a rehearsed PITR restore, and a tested migration path. 4 hours business-hours fits a pilot. **The lease must be longer than the longest single node** (LLM timeout + 30 s query timeout + commit) because it is never renewed. 120 s with factor 1.5 gives 180 s takeover, inside the 5-minute run deadline. Better still, add lease renewal on each transition and go back to 30 s, but that is a code change. |
| `reference_stack/drift/drift-policy.proposed.json` | **Amend** | All rules: `min_samples: 100`. Severity: `C-01`, `R-01`, `I-01`, `O-02` change `critical` to `warning` for the pilot. `C-02`: keep the values but mark it **inactive** until context age is collected (the reference collector leaves it empty). Other thresholds unchanged. Add a policy field or doc note: windows are per tenant, **7-day current vs. previous 28-day baseline**, and the baseline is frozen per release. | With 30 samples, a +10-point jump in a rate around 10% is about 1.3 standard errors, so expect false alerts. A p95 from 30 samples is effectively the second-largest value. At pilot volume, 100 samples per window means weekly review, which is right for advisory drift. The dashboard turns `critical` into `page`, and nobody should be paged for drift during a pilot. The baseline refresh policy is listed as an open question in ADS-058. |
| `reference_stack/drift/drift-thresholds.proposed.json` | **Approve** | as is | These are deterministic corpus gates (100% agreement, 0 false alerts, 0 writes, 0 runtime wiring). Exact gates are right for a synthetic corpus. The file honestly says it measures nothing about production alert quality. |
| `reference_stack/m7/reliability-thresholds.proposed.json` | **Approve values; amend text** | Gate values unchanged. In `not_measured`: `retry_after_failure` is stale (M7-H3 added `retry_guidance: resubmit_with_new_idempotency_key`), so it should say "retry guidance exists; client behaviour is not evaluated". Add `lease_expiry_during_live_node: "a slow live node whose lease expires is not exercised; leases are not renewed"`. | Zero wrong answers, zero unsafe outcomes, and at most 2 executions per run (the at-least-once rebuild) are correct invariants. Paying for a read twice after a crash is acceptable for a pilot. The missing scenario is the one most likely with a real LLM (finding 1). |

## Runbook tabletop results

Method: I read each runbook cold as the on-call engineer, assumed a deployed API (one or more replicas) on PostgreSQL, and checked whether
each read-only check and mitigation can actually be done with the code, endpoints, and tools that exist today.

| Runbook | Rating | Can the checks be done today? | What is missing or wrong |
|---|---|---|---|
| `ops-cost-budget` | Needs work | **No.** The dashboard tenant row is an in-process Python object, not served. No query or command is given for "count recent runs per caller and purpose". | A served usage view or SQL for the audit count. How to apply a per-tenant override (nothing loads the policy file at runtime). Cost units are uncalibrated and exclude LLM spend, so the runbook should say that warehouse- and provider-side spend dashboards come first. There is no "unblock before midnight" procedure. |
| `ops-rate-limit` | Needs work | **No** (dashboard not served). | It says refusals carry a `Retry-After` hint, but `QuotaGuardedService` raises `ServiceError(429, code)` and drops `retry_after_seconds` (ADS-066 says no header). The alert fires once per process lifetime, so its absence does not mean the problem is absent. It says nothing about multiple replicas multiplying effective limits. |
| `ops-slo-burn` | Needs work | **No.** "Compare traces by `run_ref`" needs exported traces (in-memory only). "Diagnose a failed run" needs a run ID, but traces only show `run_ref`. | A trace exporter and backend. A `run_ref` → run lookup (tenant-scoped SQL that hashes run IDs, or store `run_ref` as an indexed column). Something has to call `SloTracker.evaluate` on a schedule with deduplication. A paging target and escalation path. Steps for "is it the LLM provider?" (`planner_unavailable` counts). |
| `ops-slo-latency` | Needs work | **No** (span durations not exported; drift monitor not scheduled). | Per-layer latency source. LLM provider status and latency check. The concurrency-cap queueing claim cannot be checked without the dashboard. "Raise capacity" has no concrete action (replica count, warehouse size). |
| `ops-run-diagnosis` | Needs work | **Partly.** `diagnose_run` works but is a Python function with no CLI or endpoint, and it needs `tenant_id`, `purpose`, and the **raw run ID**, while the runbook says "by run reference". | A CLI (`python -m ... diagnose --tenant --purpose --run-id`) and the `run_ref` lookup. **Safety problem:** the "replay" check (re-submit with the same idempotency key) is not read-only. It is metered, and on an `active` run it calls `_resume` and continues execution. Change it to "use `status`; never re-submit as a diagnostic". |
| `ops-release-gate` | Usable | Yes: `make analytics-*-eval` targets and the reports exist. | Fine as an engineering pre-release runbook. It is not an on-call runbook. Add the expected runtime of each target. |
| `ops-security-finding` | Needs work | Yes for gate regressions (`make analytics-security-eval`). | It is a CI regression procedure, not incident response. Missing: containment (revoke the API key or IdP client, disable a tenant, block a purpose), evidence preservation, who to notify and when, and the customer communication owner. |
| `ops-restore` | Needs work | **Partly.** The verify, restore, and refusal codes exist, but only as Python functions, with no command given. "Fresh, migrated, empty DB" has no `alembic upgrade <rev>` step. | **Stale:** it says paused reviews fail closed (no longer true after M7-H1). It does not include the Azure PostgreSQL PITR procedure (the actual production tool). It does not say that the logical backup is not snapshot-consistent and is plaintext with request text and identity claims. Missing post-restore steps: invalidate in-process caches (restart all replicas) and re-verify quota state. |
| `ops-failover` | Needs work | **Partly.** Diagnosis yes (see above). "Wait for lease expiry, then resume" has **no operator action**, because resume only happens when the client calls again. | An operator resume command or background sweeper. The symptom "concurrency slots stay held after a crash" is inaccurate: process-local slots die with the process, and live-process slots are released in `finally`. Add the live-but-slow-worker case (lease expired while still executing, which risks a duplicate query) and how to tell it apart from a dead worker. |
| `ops-deployment-checklist` | Needs work | **No.** `run_id_key` and `min_cohort` are constructor arguments with no setting in `app/config.py` and no composition root. Shared quota state does not exist. The restore drill has never run against PostgreSQL. | Correct as a blocker list but incomplete (see Deployment readiness). Each item needs an owner and a verification command. |
| `ops-rolling-upgrade` | Needs work | Yes, the fixture tests run locally. | No ordering of migration vs. code (`alembic upgrade` before new workers, contract migrations after). No drain or lease-handover procedure for old workers. No rollback steps (downgrade path, and what happens to runs written by the new version). No web/API version skew note. |

The `drift-*` runbooks (not rated individually) all have the same blocker: **no monitor is scheduled**. Some checks are Python calls
(`current_snapshot()`). `drift-context` C-02 cannot fire in practice. `drift-latency` refers to "infrastructure dashboards" that are not
defined. The content is reasonable once there is a weekly drift job writing a report somewhere people can read it.

## Retention recommendation

Durable run material (`analytics_run_plans`, `analytics_run_policy_values`, `analytics_run_result_links`, migration 0012) currently has
no retention or purge. The table holds SQL text with bound literals, filter values, and identity claims, so it is sensitive even without
rows.

| Material | Recommended retention | Rationale |
|---|---|---|
| `analytics_run_policy_values` | Delete **when the run reaches terminal state**. Safety-net purge of anything older than **run deadline + review TTL + 24 h** (with today's 5-minute deadline, that is review TTL + ~1 day). | It is only needed to continue an in-flight run. Identity claims and filter literals should not be kept at rest after that. `discard` already exists, so call it from terminal handling. |
| `analytics_run_plans` | Keep for **30 days** after the run is terminal, then purge. | Long enough for incident diagnosis and to fingerprint-check reported wrong answers. The evidence envelope (kept longer) already holds the plan fingerprint, so audit does not need the SQL forever. |
| `analytics_run_result_links` | Purge **with the plan** (same 30 days). | A link without a plan is useless. |
| Runs, transitions, evidence, feedback, audit | Unchanged here (append-only by design). A separate owner decision is needed, likely 1 year or per contract. | Out of scope for this item, but the backup size and the PITR window depend on it. |
| Logical backups and PITR | PITR 7 days (current Terraform). Logical exports, if kept, **encrypted** and limited to **14 days**. | The backup files contain request text and identity claims in plaintext. |

The purge must be a scheduled, tenant-scoped, idempotent job that never touches in-flight runs (status not `terminal`). Its delete counts
should be logged without content. The in-process `ExecutionResultStore` and `CompiledPlanStore` maps also need eviction: drop on terminal,
plus a size cap like `PolicyValueStore.MAX_ENTRIES`. This is a memory-stability issue as much as a retention one.

**Answer rows: keep them non-durable.** Storing rows would create a second, access-controlled copy of customer warehouse data, with its own
encryption, residency, deletion, and breach scope. That is not worth it for a pilot. The costs of not storing them are acceptable:
a re-ask after a restart, and one extra read after a mid-run process crash. Two conditions apply:

- The UI and API must say clearly that old answers are "unavailable" rather than looking broken.
- Rebuilt rows reflect data at rebuild time, as ADS-075 says. Record a rebuild flag in the evidence so a reviewer can tell.

## Deployment readiness (exists / missing)

| Item | State | Notes |
|---|---|---|
| Production composition root (governed service wired into `app.main`, with durable stores on the engine) | **Missing** | `V2Runtime.service` is never set outside tests and the reference stack, so v2 returns 503. |
| `run_id_key` from a secret store | **Missing** | Constructor argument only, no setting. Key Vault exists in Terraform. |
| `min_cohort` decided and configured | **Missing** | Open finding F-03 (security owner's decision). |
| Quota guard mounted | **Missing** | `QuotaGuardedService` is never used by the app. |
| Shared quota state across replicas | **Missing** | In-process only. Azure Redis exists in Terraform and could back it. Its failure mode (fail open or closed) is an owner decision. Or run one replica for the pilot and say so. |
| Global (all-tenant) warehouse concurrency cap | **Missing** | Limits are per tenant only. |
| Warehouse-side guardrails | **Partly exists** | The PostgreSQL gateway sets `SET TRANSACTION READ ONLY` and `statement_timeout`. Still needed: a dedicated read-only role with connection limit and resource limits on the real warehouse. |
| LLM provider spend cap and timeout | **Missing / unknown** | Token cost is not attributed (ADS-066). A provider-side budget is needed. |
| Lease renewal or a lease longer than the longest node | **Missing** | See finding 1. |
| Background resume sweeper | **Missing** | Only client calls resume runs. |
| Control store backups | **Exists (infra)** | Azure PostgreSQL Flexible Server `backup_retention_days = 7` (PITR). HA is commented out, the SKU is Burstable B1ms, and public network access is enabled. Production needs General Purpose, VNet integration, and an owner choice on zone-redundant HA. |
| Restore drill on the target database | **Missing** | Drills ran on SQLite only, and the logical backup has never run against a PostgreSQL server. |
| Metrics export | **Partly exists** | `/metrics` serves the default `prometheus_client` registry, and `infra/observability/prometheus.yml` scrapes `analytics-api:8090`. The ADS-065 `Metrics` registry is not exported. |
| Trace and log export | **Missing** | In-memory only. Log Analytics exists in Terraform but is not fed by the analytics telemetry. |
| Dashboards | **Missing** | `build_dashboard` is a library. The Grafana `compass-operations.json` is not analytics-specific. |
| Alerting and paging (rules, routing, dedup, escalation, rota) | **Missing** | No Azure Monitor alert rules or action groups. Quota and SLO alerts are in-memory lists with the dedup defects above. |
| Drift job | **Missing** | No scheduler. Monitors and collector exist. |
| `run_ref` → run lookup and a diagnosis CLI | **Missing** | Needed for every diagnosis runbook. |
| Retention and purge job; in-process store eviction | **Missing** | See Retention. |
| Health and readiness | **Exists (partly)** | `/health` reports the context index and dashboard readiness. It does not check control-store connectivity, the model provider, or the warehouse. |
| Runbooks | **Exist** | 11 ops and 6 drift. Ratings above. 1 usable, 10 need work. |
| Migrations | **Exist** | Alembic through `0012`, with upgrade/downgrade tested with data on SQLite. |
| Release gates and evaluations | **Exist** | Make targets and reports. ADS-076 `answers_per_tenant_day` is unmet, and all thresholds are unapproved. |
| On-call rota, escalation, and customer communication owner | **Missing** | Human and organisational decisions. |

## Pilot view

**Ops recommendation: NO-GO today; conditional GO for a limited pilot (2–3 tenants, business-hours support, single API replica)
once these are done:**

1. Build the composition root: the governed service, durable stores, quota guard, and observability wrappers, with `run_id_key` from
   Key Vault and `min_cohort` set by the security owner.
2. Fix leases: renew the lease on each transition, or set the lease above the worst-case node duration. Add a test where a live,
   slow node outlives its lease.
3. Fix alerts: per-window deduplication for rate/concurrency alerts and SLO evaluation, a scheduled evaluator, and delivery to a real
   channel with one named pager per business day. Pages for drift stay off.
4. Cost safety: an LLM provider spend cap, a read-only warehouse role with limits, the amended quota values, and one week of shadow
   calibration samples (M7-H4) before quotas are trusted.
5. Retention: purge policy values on terminal, evict the in-process stores, and schedule the plan purge job.
6. Run one restore rehearsal with Azure PITR on a staging copy, timed against the amended RTO.
7. Correct the four inaccurate runbooks (rate-limit Retry-After, run-diagnosis replay safety and `run_ref`, restore staleness, failover
   resume path), and add a `run_ref` lookup and diagnosis CLI.
8. The owner approves or amends the proposed files (this review does not), and the approvals are recorded in the program manifest.

Run a single replica during the pilot unless shared quota state is built. That makes the in-memory quota a known, documented limit
rather than a silent multiplier. Hold a real human tabletop on staging once items 1–3 are done.

## Questions for the human owner

1. Pilot shape: how many tenants, how many users, what support hours, and will you run one replica (so shared quota state is not needed
   yet)?
2. Which LLM provider and model will the pilot use, and what monthly spend cap per tenant and overall?
3. Which warehouse, and can you give the pilot a dedicated read-only role with connection and resource limits?
4. Do you accept RPO 5 minutes (PITR) and RTO 4 hours business-hours for the pilot, and will you authorise one staging PITR restore
   rehearsal?
5. Lease fix: renewal (code change, keeps 30 s) or a longer lease (config only, slower takeover)?
6. Retention: do 30 days for plans and links and delete-on-terminal for policy values fit your data obligations? What is the retention
   for runs, evidence, and feedback?
7. Do you confirm answer rows stay non-durable, so users re-ask after restarts?
8. Who is paged, through which channel, and who owns customer communication during an incident?
9. Should the SLO measure per-call latency (current) or end-to-end time-to-answer, excluding human review time?
10. Should quota-store failure (if Redis is added) fail open or closed?
