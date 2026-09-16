# ADS-010: Ontology and Provenance Contracts

Status: **Complete**
Milestone: M1
Depends on: ADS-008

## Deliverable

`packages/platform_contracts/ontology.py` defines versioned tenant-scoped
ontology nodes, edges, provenance records, lifecycle state, and temporal
validity. `OntologySnapshot` rejects duplicate IDs, cross-tenant objects,
unknown edge endpoints, self-edges, missing provenance, and invalid time ranges.

## Evidence

- `packages/platform_contracts/tests/test_ontology.py`
- JSON round-trip, cross-reference, tenant isolation, temporal, and provenance
  tests pass.

## Boundary

The contracts describe immutable context facts. They do not merge competing
sources, certify semantics, execute SQL, or authorize tools.
