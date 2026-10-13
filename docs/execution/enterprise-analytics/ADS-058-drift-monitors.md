# ADS-058: Drift Monitors for Context, Retrieval, Intent, Outcomes, Latency, and Cost

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M5 (wave 5D, first of ADS-058 and ADS-059)
Depends on: ADS-049, ADS-057

## Decisions confirmed by the user

Wave 5D scope ("go with that scope for 5D"): local and fakes only; thresholds recorded as proposed, not approved;
a monitor module with a synthetic drift corpus and runbooks for ADS-058, and an adversarial feedback corpus for ADS-059.

## Deliverable

- `packages/platform_contracts/drift.py`: `RunObservation` (numbers and codes only: outcome, error codes, retrieved item
  count, context age, latency, cost; extra fields are forbidden so no request text, SQL, rows, or reasons can ride
  along), `DriftRule`, `DriftPolicy` (unique rule IDs; each rule points at its own monitor's runbook; an "approved"
  policy must say who approved it and when), `DriftAlert`, `SkippedRule`, `DriftReport`.
- `app/drift/monitors.py`: pure, deterministic statistics and `evaluate_drift(baseline, current, policy)`. Ten rules
  across six monitors: stale-context rate and maximum context age (context); empty-retrieval rate and mean retrieved
  items (retrieval); malformed-intent and clarification rates (intent); outcome-mix total-variation distance and
  success rate (outcomes); p95 latency ratio (latency); mean cost ratio (cost). Comparisons are inclusive. A rule with
  too few samples in either window, no data, or a zero baseline for a ratio is **skipped and reported**, never guessed.
- `app/drift/collect.py`: read-only extraction of observations from terminal runs in the control store.
- `app/drift/alerts.py`: an `AlertSink` (an in-memory sink for now), and runbook lookup/validation.
- Six runbooks in `docs/execution/enterprise-analytics/runbooks/` (`drift-context`, `-retrieval`, `-intent`, `-outcomes`,
  `-latency`, `-cost`), each with Symptom, Likely causes, Read-only checks, Mitigation, and Do not. Mitigation is always
  a person's reviewed action.
- `reference_stack/drift/drift-policy.proposed.json` (the alert rules, **status `proposed`**), an 18-case synthetic
  corpus with hand-written expected alerts, and proposed gate thresholds. `make analytics-drift-eval` writes
  `reports/ADS-058-drift-report.{md,json}`.
- **Advisory only.** An alert starts no rollback and changes no run, release, pointer, or threshold. Nothing in the
  runtime or API imports the monitors (tested), and no endpoint or scheduler runs them.

## Evidence

- `tests/test_ads058_drift.py` (15 tests): policy and contract validity and the repository policy staying proposed;
  observations carry no content; exact statistics; each monitor trips its own rule and nothing else; thresholds are
  inclusive and improvements never alert; insufficient data and a zero baseline are skipped; alerts carry severity,
  runbook, and the numbers behind them; reports are reproducible; every rule's runbook exists with every required
  section; observations are extracted from real reference-stack runs (answered and refused) without writing and
  stay tenant- and window-scoped; no runtime module depends on the monitors; the corpus meets its proposed
  thresholds, and a wrong expectation or a changed corpus is detected.
- `make analytics-drift-eval`: 18/18 hand-written cases pass and all ten proposed gates are met.

## Proposed thresholds (NOT APPROVED)

Two things await the user, both recorded as proposed:
1. **The alert rules** (`reference_stack/drift/drift-policy.proposed.json`): for example stale-context +10 points,
   empty retrieval +10 points, malformed intent +5 points, clarification +15 points, outcome-mix distance 0.25,
   success rate -10 points, p95 latency 1.5x, mean cost 1.5x, context older than 72 hours, minimum 30 runs per window.
   They were chosen without production data.
2. **The corpus thresholds** (`reference_stack/drift/drift-thresholds.proposed.json`): case agreement, recall, runbook
   coverage, and silence gates 100%; false alerts, monitor writes, runtime wiring, and protected-file writes 0.

## Boundary

- Windows are synthetic. Real alert precision and recall, seasonality, and correct thresholds need production data;
  a window comparison against a fixed baseline also needs a policy for when the baseline itself is refreshed.
- Alerts go to an in-memory sink. Paging, dashboards, deduplication, and on-call routing are not built.
- Context age comes from an optional callable; the reference collector leaves it empty, so the age rule is only
  exercised on synthetic windows.
- Drift detection is per tenant window; cross-tenant aggregation is not done.
- Monitors observe outcomes, not correctness: a wrong but validated answer does not drift any statistic.
