# ADS-021: Deterministic Provider Fakes

Status: **Complete**
Milestone: M2
Depends on: ADS-020

## Deliverable

`services/analytics-api/app/harness/fakes.py` provides local contract-shaped
fakes for identity, metadata catalog, certified semantic registry, structured
model output, policy decisions, and warehouse results. Fakes copy inputs and
outputs at the boundary, record relevant calls, and fail explicitly when a
fixture is missing instead of inventing data.

## Evidence

- `services/analytics-api/app/harness/fakes.py`
- `services/analytics-api/tests/test_harness_m2.py`
- Identity, catalog, registry, model, policy, and warehouse fake behavior is
  covered without network access.

## Boundary

These providers are test authorities only. They cannot be selected by a
production request path and do not replace live adapters.
