# ADS-069 operations drill (seeded failures)

| Scenario | Runbook | Diagnosed | Replayed identically |
|---|---|---|---|
| cost-budget-exhausted | ops-cost-budget | True | True |
| rate-limited | ops-rate-limit | True | True |
| slo-fast-burn | ops-slo-burn | True | True |
| slo-latency | ops-slo-latency | True | True |
| policy-refused-run | ops-run-diagnosis | True | True |
| corrupt-backup | ops-restore | True | True |
| failing-security-gate | ops-security-finding | True | True |

Runbooks checked: 11; problems: 0.
Result: PASS
