# Analytics Operations Runbook

## Query Incident

1. Find the correlation/query ID in structured ingress, planning, compilation,
   execution, evidence, and audit events.
2. Check tenant budget, gateway health, cancellation state, policy decision,
   and warehouse error before retrying.
3. Do not replay a restricted query without resolving the policy decision.

## Release Rollback

Stop the canary, preserve the evaluation and audit evidence, roll back to the
registered immutable component version, and rerun the pinned suite. A rollback
is not complete until the tenant and policy negative tests pass.

## Restore Drill

Restore the analytics control store into an isolated target, verify its backup
digest and object count, run migrations, and verify query-outcome/audit
integrity. Record RPO, RTO, missing objects, and customer impact.

## Alerts

Availability, p95 latency, error rate, evaluation pass rate, and cost alerts
must link to a named owner and this runbook. Customer-specific thresholds and
pager routing are configured during the pilot; this repository contains only
the vendor-neutral evaluation contracts.
