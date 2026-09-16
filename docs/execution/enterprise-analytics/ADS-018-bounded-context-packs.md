# ADS-018: Bounded Context Packs

Status: **Complete**
Milestone: M1
Depends on: ADS-017

## Deliverable

`build_context_pack` deterministically converts OpenSearch candidates into a
small evidence pack. Candidates are ranked by score with asset-id tie
breaking, filtered to the snapshot's certified assets, cited with their
snapshot identity, and admitted only while the configured token budget holds.
From selected certified ontology nodes it performs bounded, deterministic edge
closure. Only edges whose endpoints are certified are included, and both graph
depth and edge count are bounded. Omitted candidates and edges are reported so
callers can distinguish deliberate compression from missing retrieval.

## Evidence

- `packages/platform_contracts/context_snapshot.py`
- `services/analytics-api/tests/test_context_m1.py`
- Certified filtering, tenant/snapshot scope, deterministic ordering, citation,
  graph closure, and bounded-pack assertions pass.

## Boundary

The pack is input evidence for later planning and agent execution. It is not a
generated answer and does not authorize tool calls.
