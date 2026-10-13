# M7 hardening (built after the M7 evaluations, on the user's instruction)

Status: **Review** (implemented and locally verified; none of it is independently reviewed)

These four items came out of the ADS-073, ADS-075, ADS-076, and ADS-078 findings. They are not plan packets and have no manifest task.

## M7-H1: durable plan and policy-value storage
- Migration `0012_durable_run_material`: `analytics_run_plans`, `analytics_run_policy_values`, `analytics_run_result_links`. A plan is SQL plus bound parameters (datetime, date, and Decimal kept exact); policy values are small filter literals and identity claims. **No rows are stored.**
- `CompiledPlanStore`, `PolicyValueStore`, and `ExecutionResultStore` take an optional engine. A result missing after a crash is rebuilt by `resume` (used only by the result-validation and explanation nodes of an in-flight run), by running the stored plan again; a status read never runs a query.
- Effect: all 26 process-crash points of the ADS-075 matrix end in a correct answer (before: 10 failed closed). A crash after the query costs one extra read (at-least-once). Paused reviews survive a restart or restore.
- Boundary: the durable tables are included in backups but have no retention or purge job; a retention rule for plans and policy values is a decision for the owners.

## M7-H2: intent-echo check
See the update in `ADS-073-abstention-evaluation.md`. Refusals use reason `unsupported_request` with a content-free explanation of the mismatch.

## M7-H3: retry guidance
`AnalyticsFailedOutcome.retry_guidance` is `resubmit_with_new_idempotency_key` for retryable failures (the web client's "Try again" already used a new key; the TypeScript type gained the optional field, web tests could not be run here because `node_modules` is absent).

## M7-H4: cost-unit calibration mechanism
`packages/platform_contracts/cost_calibration.py`, `app/execution/calibration.py`, `make analytics-cost-calibration`. A fit from measured samples is a **proposal**; an unapproved or non-production calibration is never applied, and an approval needs a named person and date. **No real warehouse calibration was done**: it needs real samples, which this environment does not have. The local measurement shows the raw estimates do not predict local elapsed time (for example a 200-unit query is among the cheapest), which supports calibrating before relying on quotas. ADS-076's `answers_per_tenant_day` gate is therefore **unchanged and still unmet**. To calibrate: collect `[{dialect, estimated_units, observed}]` from the real warehouse, run `python -m reference_stack.calibration_eval samples.json`, review the proposed fit, and have the owner approve it.
