# ADS-034: Certified Ontology Resolution

Status: **Complete**
Milestone: M3
Depends on: ADS-032, ADS-033

## Deliverable

The resolver maps model-proposed aliases only through certified ontology nodes
whose IDs exist in the exact certified semantic contract. Canonical contract
IDs take precedence over aliases; collisions become a targeted clarification,
and unknown, candidate, deprecated, cross-tenant, or uncertified IDs cannot
advance to planning. The fully resolved intent is validated against the exact
contract version.

## Evidence

- `services/analytics-api/app/runtime/ontology_node.py`
- `packages/platform_contracts/ontology.py`
- `packages/platform_contracts/analytics_intent.py`
- Static validation: Ruff and `git diff --check` pass.

## Boundary

Ontology snapshot publication and human semantic certification remain outside
this handler. M1 certification is still a separate gate.
