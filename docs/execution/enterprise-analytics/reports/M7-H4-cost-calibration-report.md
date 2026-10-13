# M7-H4: Cost-unit calibration mechanism

**Mechanism checks: all pass.** This is not a warehouse calibration and no calibration is applied by default.

| Check | OK | Detail |
|---|:---:|---|
| a known scale and offset are recovered | yes |  |
| too few samples are refused | yes | too_few_samples:d |
| constant estimates are refused | yes | estimates_do_not_vary:d |
| estimates that do not predict cost are refused | yes | estimates_do_not_predict_cost:d |
| a proposed calibration is not applied | yes |  |
| an approved but non-production calibration is not applied | yes |  |
| an approved production calibration is applied for its own dialect only | yes |  |
| approval without a named person is refused | yes |  |

## Local measurement (informational)

| Engine | Question | Estimated units | Median ms |
|---|---|---:|---:|
| duckdb | What is total revenue | 200 | 7.92 |
| duckdb | Revenue by status | 263 | 7.30 |
| duckdb | Show monthly revenue | 40 | 7.47 |
| duckdb | Top revenue status | 263 | 15.04 |
| postgres | What is total revenue | 25 | 9.48 |
| postgres | Revenue by status | 25 | 9.03 |
| postgres | Show monthly revenue | 25 | 10.74 |
| postgres | Top revenue status | 25 | 11.26 |

## Limits

- This is not a warehouse calibration. Real warehouse samples (estimated units and the observed cost in the chosen unit) are needed, and a person must approve the fitted calibration.
- Local DuckDB over 100 rows and an emulated PostgreSQL do not stand in for the target warehouse.
- No calibration is applied anywhere by default; the quota gate answers_per_tenant_day in ADS-076 is therefore unchanged.
