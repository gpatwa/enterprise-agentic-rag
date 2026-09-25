# ADS-037: Policy, Compile, and Estimate Gates

Status: **Complete**
Milestone: M3
Depends on: ADS-036

## Deliverable

Graph-v2 orders exact certified validation, authorization, compilation, and
cost estimation. Authorization aggregates every applicable policy; any
purpose denial wins, while required row filters are passed as parameters to the
compiler. Sensitive policy values are held in a tenant/run-scoped, one-time
process-memory handoff, not copied into the durable run state. Compilation
cannot proceed without an explicit allow decision and policy-value reference.

The compiler emits only a plan reference into graph state. Cost estimates are
bounded by the run budget and can produce a durable human-approval pause.
Warehouse execution remains an injected fake in M3.

## Evidence

- `services/analytics-api/app/security/authorization.py`
- `services/analytics-api/app/runtime/governed_stages.py`
- `services/analytics-api/app/compiler/service.py`
- Static validation: Ruff and `git diff --check` pass.

## Boundary

Policy-value handoff and compiled-plan storage are local process-memory
implementations; a restart fails closed. Durable/customer-data-plane compiler
and warehouse adapters belong to later milestones. No SQL is executed here.
