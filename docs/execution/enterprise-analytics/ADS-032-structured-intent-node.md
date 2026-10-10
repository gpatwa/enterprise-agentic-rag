# ADS-032: Structured Intent Extraction

Status: **Complete**
Milestone: M3
Depends on: ADS-018, ADS-030

## Deliverable

`app/runtime/intent_node.py` defines one bounded call to an injected structured
intent client. Its response is parsed as `AnalyticalIntent` (extra fields are
forbidden), then bound to the request ID and tenant. The contract has no SQL or
executable-expression field. Malformed output fails closed; the node does not
retry.

The node consumes the bounded context pack and advances on graph-v2 to ontology
resolution. The model client is injected so local fakes and production adapters
share the same schema boundary.

## Evidence

- `packages/platform_contracts/analytics_intent.py`
- `services/analytics-api/app/runtime/intent_node.py`
- `services/analytics-api/app/runtime/graph_factory.py`
- Static validation: Ruff and `git diff --check` pass.

## Boundary

This packet defines the provider protocol; it does not call a live model or add
an unbounded retry path. Semantic IDs are still re-resolved and certified by
ADS-034 and ADS-036 before compilation.
