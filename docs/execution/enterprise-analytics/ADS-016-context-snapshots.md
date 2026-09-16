# ADS-016: Immutable Context Snapshots

Status: **Complete**
Milestone: M1
Depends on: ADS-015

## Deliverable

`packages/platform_contracts/context_snapshot.py` defines the versioned
`ContextSnapshot` contract. A snapshot is tenant-scoped, immutable at the
model boundary, and content-addressed with a deterministic SHA-256 fingerprint
over its source fingerprints, merged metadata assets, ontology, and semantic
contract references. Build-time ordering makes equivalent inputs produce the
same fingerprint; changed source evidence produces a different fingerprint.

The same module defines cited `ContextPack` and `ContextPackItem` contracts for
the bounded serving path. Packs retain the snapshot and tenant identity and
cannot exceed their declared token budget.

## Evidence

- `packages/platform_contracts/context_snapshot.py`
- `services/analytics-api/tests/test_context_m1.py`
- Round-trip, deterministic fingerprint, changed-source, forged-fingerprint,
  scope, and token-budget tests pass.

## Boundary

This packet creates trusted context artifacts. It does not call an LLM, grant
runtime data access, or execute an agent action.
