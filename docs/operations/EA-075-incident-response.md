# EA-075 Incident Response And Support Process

## Severity

| Severity | Examples | Initial owner | Target acknowledgement |
|---|---|---|---|
| P0 | tenant isolation, secret exposure, destructive policy bypass | Security + incident commander | 15 minutes |
| P1 | pilot-wide outage, material data corruption, repeated query failure | Engineering on-call | 30 minutes |
| P2 | degraded latency, single connector failure, non-critical drift | Support owner | 4 hours |
| P3 | question, documentation, low-impact defect | Product support | 1 business day |

## Response

1. Create an incident ID and preserve audit/correlation IDs.
2. Contain access or traffic; do not delete evidence before retention review.
3. Determine affected tenants, data classes, time window, and subprocessors.
4. Notify the customer owner according to the DPA and severity policy.
5. Roll back or disable the affected component only through the governed
   rollout path.
6. Record root cause, corrective action, regression case, and customer update.

Run a tabletop before pilot launch. Contact names, paging targets, customer
notification windows, and regulatory obligations are external inputs.
