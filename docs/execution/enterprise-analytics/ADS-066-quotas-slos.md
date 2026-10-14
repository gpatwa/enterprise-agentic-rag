# ADS-066: Per-Tenant Quotas, SLOs, Cost Attribution, and Alerts

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M6 (wave 6C)
Depends on: ADS-065

## Decisions made under the user's delegation ("make the decision")

1. **Everything is keyed by tenant.** Rate, concurrency, and the daily cost budget are per tenant, so one tenant exhausting its quota cannot
   consume another's; the manager holds counts and cost units only, never request text, rows, SQL, or user identifiers.
2. **Admission happens before anything runs.** Analyze, clarify, and review (each can execute a query) are admitted first; an exhausted
   tenant costs the platform no warehouse work. Reads (status) are not metered.
3. **Cost is attributed from the sealed evidence**, once per run, by purpose and warehouse dialect, when the run reaches a terminal
   state. Because cost is only known after a run finishes, runs already in flight can overshoot the daily cap slightly; the overshoot is
   bounded by the concurrency cap times the per-run cost, and the scenario test asserts that bound.
4. **The daily budget resets at 00:00 UTC**; concurrency and rate state carry over. Budget alerts fire once per condition per day.
5. **SLO errors are system failures only.** A refusal the caller caused (403, a policy denial) does not burn the error budget; a
   `failed` outcome or a 5xx does. Alerts use two burn-rate windows (5 minutes pages, 1 hour tickets) and a minimum request count so a
   quiet tenant cannot page.
6. **The limits are a proposed policy.** They were chosen without production data; the manager enforces any policy it is given.

## Deliverable

- `packages/platform_contracts/quotas.py`: `TenantQuota`, `SloObjective`, `QuotaPolicy` (default, per-tenant overrides, approval block),
  `OpsAlert` (kind, severity, tenant, value, threshold, runbook).
- `app/quotas/manager.py`: `QuotaManager` (token-bucket rate limit, concurrency cap, daily cost budget, attribution, deduplicated
  alerts) and `SloTracker` (burn rates and latency over sliding windows).
- `app/quotas/guard.py`: `QuotaGuardedService`, a wrapper over the governed service that admits, runs, releases, attributes cost, and
  records the SLO event; refusals are `ServiceError(429, code)`.
- `app/quotas/simulation.py`: a deterministic load simulator (`simulate`, `FakeClock`), reused by the ADS-076 load evaluation.
- `services/analytics-api/quotas/quota-policy.proposed.json` (**status `proposed`**). Nothing mounts any of it.

## Evidence

- `tests/test_ads066_quotas.py` (13 tests): policy validity and the repository policy staying proposed; the token bucket (burst, retry-after,
  refill capped at the burst, per-tenant isolation); concurrency capped, released, never negative, and held under 16 real threads; the daily
  budget blocks, attributes once per run by purpose and dialect, and resets at midnight UTC; alerts fire once per condition per day with
  runbooks; **a noisy neighbour** (50 requests per second for 10 seconds) is held to its burst plus rate and concurrency cap while **every
  request of the quiet tenant is served** and only the noisy tenant alerts; **a denial of wallet** (200 expensive queries) stops at the
  budget with bounded overshoot while the honest tenant is untouched; with the real service behind the guard, three runs execute and the
  rest are refused with 429 before executing any statement; slots are released on failure, status is not metered, and throttled
  requests never reach the service; SLO burn rates page, ticket, stay quiet on little traffic, and age out; user-caused refusals do not
  burn the budget and slow runs raise a latency alert; and quota state holds counts and costs only.

## Boundary

- Simulated load, not real load: the scenarios prove admission and accounting under scripted arrivals and a fake clock. Real latency,
  contention, and the unit economics at target load are ADS-076.
- The cost unit is the gateway's planner unit, which differs per dialect and is uncalibrated against money; a budget in "cost units" is not
  a budget in currency until a calibration exists. Model/token cost is not attributed yet.
- State is in process memory: a restart forgets usage, and multiple API replicas would each hold their own counts. A shared store
  (and its failure modes) is part of ADS-068's high-availability work.
- No HTTP `Retry-After` header is set; the 429 carries a code only.
- The reference stack serves one tenant's context, so cross-tenant behaviour with the real service is shown at the admission layer.
