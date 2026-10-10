# IMD-042: CPU Learned-Ranker Decision ADR

## Objective

Record a bounded offline spike and decision criteria for one CPU learned
ranker. Compare a deterministic linear baseline, LightGBM, XGBoost, and neural
options on fixed local criteria; select at most one CPU ranker for IMD-043 and
defer neural serving. This packet produces an ADR/spike report only.

## Dependencies and Reads

- IMD-041 is merged. Read training examples, ranking contracts, evaluation
  metrics, repository dependency policy, and the canonical plan.

## Owned Files

- Create `docs/adr/ADR-IMD-042-cpu-ranker.md`.

Do not modify requirements/lock files, training code, inference, API, cloud,
support, analytics, or web files.

## Requirements

- Use fixed criteria: CPU latency, deterministic reproducibility, missing-value
  handling, small-data quality, explainability, install footprint, license,
  and local demo cost.
- Make explicit that synthetic offline evidence is not production lift.
- Select a conservative CPU option or explicitly defer dependency installation;
  record rollback/reopen conditions and neural deferral.

## Validation

```bash
git diff --check
```

## Commit

```text
docs(discovery): record cpu ranker decision
```
