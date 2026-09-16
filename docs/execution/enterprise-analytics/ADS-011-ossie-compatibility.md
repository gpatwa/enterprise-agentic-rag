# ADS-011: Apache Ossie Compatibility

Status: **Complete**
Milestone: M1
Depends on: ADS-008, ADS-010

## Deliverable

`packages/platform_contracts/ossie.py` implements the pinned `0.2.0.dev0`
subset defined by `ads-008.v1`. Imports produce draft Compass semantic
documents and a compatibility report. Exports emit only the portable subset
and may preserve Compass lifecycle and tenant data in a namespaced extension.

Unknown Ossie versions are rejected. Unsupported or lossy expressions are
reported and never become executable SQL, policy, or certification authority.

## Evidence

- `packages/platform_contracts/tests/test_ossie.py`
- Import/export JSON round-trip, draft lifecycle, report, extension, and
  unknown-version rejection tests pass.

## Boundary

Ossie is an interchange format, not the Compass runtime contract. Imported
models require normal ownership, provenance, policy, and certification review.
