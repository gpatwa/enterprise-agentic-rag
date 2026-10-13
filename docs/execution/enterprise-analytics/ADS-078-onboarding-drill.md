# ADS-078: Second-Tenant and Apache Ossie Portability Onboarding Drill

Status: **Review** (local drill with a sandbox registry; thresholds **proposed, not approved**; **no certification was performed**)
Milestone: M7 (wave 7B)
Depends on: ADS-011, ADS-064

## Decisions made under the user's delegation ("make the decision")

1. **Onboard through data, not code.** A hand-written Ossie model for a second tenant (subscriptions) is imported with the existing `import_ossie`. The import is a **draft** with no policies and is not certification-eligible.
2. **A draft is inert.** It is refused by `get_certified` and by the compiler. Only in a **temp copy of the registry** does the drill flip the lifecycle and the metric to certified (what the owner would do in Git). That flip is a drill
   transformation, not a certification; the repository registry is never written (a test checks its contents).
3. **Compile and run on the tenant's own data**, compared with an independent oracle (60 invoices, monthly totals), using the existing compiler and DuckDB gateway.
4. **Isolation both ways**: the first tenant cannot use the second tenant's contract and the second cannot use `sales-core` (the certification gate refuses both).
5. **No code or contract-schema change**: a digest of `app/`, `packages/platform_contracts/` (non-test), the repository registry, and the JSON schemas of `SemanticContract` and `AnalyticalIntent` is equal before and after.
6. **Hostile expressions** (a ratio, an injected `; DROP TABLE`, a subquery, an unknown dataset) are reported lossy and dropped; only `mrr` becomes a metric.

## Findings and limits

- **Ossie export now carries metrics and time-dimension flags** (changed after the user said "go ahead" on the recommendation; no Compass schema change). The first drill run showed 2 omissions on a round trip; it now shows 0 and `round_trip_omissions` is a `<= 0` gate.
- An import carries **no policies**, so nothing is answerable until a human adds them; the report lists the manual steps (review, policies, certification, context snapshot and ontology, data source and gateway).
- The reference stack's scripted model understands only the first tenant, so end-to-end natural-language onboarding of tenant B is **not** shown; the drill runs an intent.

## Deliverable

- `reference_stack/onboarding_eval.py`, `m7/onboarding-thresholds.proposed.json`, `make analytics-m7-onboarding`, report `reports/ADS-078-onboarding-report.{md,json}`, `tests/test_ads078_onboarding.py`
