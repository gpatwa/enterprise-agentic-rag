# ADS-041: Result Shape, Grain, Invariant, and Fingerprint Validation

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M4
Depends on: ADS-040

## Deliverable

`app/execution/result_validation.py` validates an `ExecutionResult` against the
certified intent, contract, compiled plan, and an independent control query. The
verdict is a `ResultValidationReport` (`valid`, `valid_with_warnings`, `invalid`)
whose issue details describe the check and never contain row values.

- **Truncation:** `truncated_max_rows` / `truncated_max_bytes` are blocking; the
  result is partial and cannot support an answer.
- **Shape:** exact `dimension_i…metric_j…` columns and row widths; metric cells
  must be finite numbers (counts non-negative integers, no nulls).
- **Grain:** duplicate group keys, and an ungrouped aggregate not returning
  exactly one row, are blocking.
- **Limit and sort:** more rows than the intent limit and out-of-order rows are
  blocking; reaching the limit is a `limit_reached` warning.
- **Totals (fanout, missing groups, invalid totals):** `control_intent` (same
  metrics, filters, and time range, no grouping, limit 1) is run through the same
  governed path by `run_control_totals`. Additive metrics (sum, count) must add
  up: groups above the total are `fanout_suspected`, below are
  `missing_groups_suspected`. Min/max must equal the control value; averages must
  lie within the group range; distinct counts within `[max group, sum of groups]`
  (`invalid_total`). A partial or limit-reached result skips reconciliation with a
  warning. A missing control total blocks by default.
- **Fingerprints:** `result_fingerprint` (canonical across numerically equal
  decimals) and `plan_fingerprint` are bound into `report.fingerprint`; an
  `expected_fingerprint` mismatch is `fingerprint_mismatch`, and a result from a
  different dialect than the plan is `dialect_mismatch`.
- `result_validation_node` (`app/runtime/result_stage.py`) gates `result_validate`:
  blocking issues fail the run with `result_invalid`, a failed control query with
  `control_query_failed`, and missing or foreign references with
  `result_inputs_unavailable`. Valid results go to `explain` with a decision
  evidence reference carrying the report fingerprint.

## Evidence

- `services/analytics-api/tests/test_ads041_result_validation.py` (16 tests): a
  real DuckDB join-fanout trap, a dropped group, truncation, and the graph node,
  plus hand-built results for bounds, shape, grain, sort, limit, fingerprints, and
  value redaction. One real bug found and fixed while testing: reconciliation
  must skip metrics whose values are already malformed.

## Boundary

- The compiler is single-dataset today, so fanout can only appear from a wrong or
  tampered plan; the control-total check is what catches it, and it will matter
  more when joins arrive. Ratio metrics are not reconciled.
- Detection is sound only for the invariants above; it does
  not prove business correctness. A control query that shares a bug with the
  primary (for example a wrong filter) would not catch it.
- Nothing yet builds `control_totals` for a production graph (policy values for
  the control compile must be supplied by the caller); persisting the report as
  evidence is ADS-042. No live database was used; DuckDB is embedded and
  PostgreSQL remains unexercised against a server.
