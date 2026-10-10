# IMD-055: Offline Drift, Calibration, Slice, and Regression Gates

## Objective

Add deterministic monitoring gates for ranking quality across new users/items,
locale/device, genre, creator size, age band, and safety classes. Gates must
cover drift, calibration, slices, regression, and missing-data behavior.

## Dependencies and Reads

- IMD-007, IMD-039, IMD-044, and IMD-054 are merged.

## Owned Files

- Create `services/discovery-api/app/monitoring/gates.py`.
- Create `services/discovery-api/tests/test_monitoring_gates.py`.

## Requirements

- Use versioned thresholds and deterministic reports; reject ambiguous cohorts,
  non-finite values, insufficient samples, and metric-version mismatch.
- Make pass/fail reasons and degraded/missing evidence explicit; no automatic
  promotion or user-facing mutation.
- Keep slice labels bounded and redact query/profile/private social values.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_monitoring_gates.py -q
ruff check services/discovery-api/app/monitoring/gates.py services/discovery-api/tests/test_monitoring_gates.py
git diff --check
```

## Commit

```text
feat(discovery): add offline monitoring gates
```
