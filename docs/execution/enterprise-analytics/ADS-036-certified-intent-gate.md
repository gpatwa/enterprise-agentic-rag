# ADS-036: Certified Intent Gate

Status: **Complete**
Milestone: M3
Depends on: ADS-034

## Deliverable

The validation node requires an exact `certified` registry document and
validates tenant, dataset, metric, dimension, and field references before the
graph can reach policy or compilation. Uncertified/exploratory intent may enter
a durable human-review pause, but an approval does not promote the contract or
send the intent to compilation; semantic certification remains a separate
governed action.

## Evidence

- `services/analytics-api/app/runtime/certification_node.py`
- `services/analytics-api/app/semantic_registry/registry.py`
- `services/analytics-api/app/runtime/graph_factory.py`
- Static validation: Ruff and `git diff --check` pass.

## Boundary

No model-generated semantic definition can certify itself. Human M1 semantic
certification and live registry publishing remain pending gates.
