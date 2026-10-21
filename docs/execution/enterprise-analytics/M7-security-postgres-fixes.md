# M7 security, PostgreSQL, and runtime fixes (from the persona reviews)

Status: **Review** (implemented and verified locally, including against a temporary local PostgreSQL 17 server; not an independent review)
Source: `persona-reviews/security-lead.md`, `persona-reviews/independent-code-review.md` (D1..D19), `persona-reviews/sre-operations.md`, `persona-reviews/data-owner.md`.
Decided by the implementing agent under the user's instruction "go ahead and make decision".

## Fixed

| Finding | Fix | Evidence |
|---|---|---|
| Any colleague could approve a paused review | `decide_review` requires the `analytics-reviewer` group (403 `reviewer_role_required`); the requester and automated or delegated callers still cannot decide | `test_review_pause_requires_a_different_reviewer_and_then_answers`; ADS-074 probes |
| F-05 / D7: a colleague could read another person's rows | `status` is requester-only; a reviewer may open the run but an answer is replaced by `refuse / unauthorized` (no rows); everyone else gets 403 `not_run_requester`. F-05 marked resolved; GAP01 closed | ADS-067 corpus (31 cases), new ADS-074 gate `same_tenant_overreach` |
| F-02: derivable run IDs | `GovernedAnalyzeService(require_run_id_key=True)` refuses to start without a key of at least 32 bytes; the pilot wiring sets it outside `dev` | `test_a_deployment_that_requires_a_run_id_key_refuses_to_start_without_a_strong_one` |
| Any group skipped the confidential review; restricted was never denied | `SemanticPolicy.allowed_groups` (additive, optional); restricted is denied and confidential goes to review unless the caller is in a named group | `test_any_group_no_longer_unlocks_confidential_and_restricted_data_is_denied_without_a_named_group` |
| App shell unsafe by default | Production refuses to start without `ANALYTICS_API_KEY`; the legacy v1 query endpoint (model-written SQL, no identity) is off in production unless `ANALYTICS_V1_ENABLED=true`; `/health` reports a short error code instead of raw text | config |
| D1 (PostgreSQL): live leases looked expired (string comparison) | timestamps compared as aware datetimes | `test_m7_postgres_control_store.py` (PostgreSQL) |
| D3 (PostgreSQL): restore left the outbox sequence behind | `setval` for every serial column after restore | same file; fails if the reset is removed |
| D4: leases never renewed | `ControlStore.renew_lease`; the runner renews before every node | PostgreSQL lease test |
| D2: lost race returned HTTP 500; any IntegrityError read as a duplicate create | `StaleWorkerError` handled like a held lease; a non-duplicate IntegrityError is 503 `control_store_conflict` | suite |
| D5: unbounded in-memory stores | `BoundedDict` (2,000 entries, oldest first) for results, explanations, validation reports, plans | suite |
| D6: shared rebuild hook | rebuilders are registered per tenant | `test_m7h1_durable_material.py` |
| D9: backups not a consistent snapshot | one read transaction (PostgreSQL: repeatable read, read only) | ADS-068 tests |
| D12: plan fingerprint ignored bound values | the reference covers the canonical parameters | suite |
| D13: policy values kept for ever | `app/resilience/retention.py::purge_run_material`: policy values deleted when the run ends, plans and links after 30 days, paused runs untouched | `test_m7_retention.py` |
| D16: negative calibration intercept | refused (`negative_intercept`) | `test_m7h4_cost_calibration.py` |
| D17: fencing restarted after a pause | fencing is `max(lease, run) + 1` | suite |
| D18: lease tokens from a timestamp | random tokens | suite |
| Data owner: corpus case A043 contradicted its question | reworded; ordering limitation recorded in the corpus approval file | corpus digest updated (still unapproved) |

## Deferred, with reasons

| Finding | Why not now |
|---|---|
| Served app does not mount the governed v2 service | separate pilot-wiring change (configuration, model, identity provider) |
| D8 rollout pointer has no tenant | the runtime does not read the rollout pointer yet |
| D10 lazy evidence sealing | needs sealing at the terminal transition; no data exposure |
| D11 quota attribution across replicas | quota state is process-local; the pilot runs one replica |
| D14 review decide race | low; reviews are single-reviewer in the pilot |
| D15 observed cost always 0 | needs the gateway to report actual cost; depends on calibration |
| D19 outbox has no consumer | no consumer exists yet; retention handled by the purge job above for the working tables |
| Gross vs net revenue in the reference contract | a data-owner decision |
| A scheduled job for the purge | part of the deployment (a Container Apps job) |
