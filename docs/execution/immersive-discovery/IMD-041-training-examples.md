# IMD-041: Point-in-Time Training Examples

## Objective

Build deterministic exposure-aware training examples from events, features,
and ranking contracts. Labels must use only information available after the
impression while distinguishing skip from unexposed.

## Dependencies and Reads

- IMD-005, IMD-017, IMD-018, and IMD-040 are merged.

## Owned Files

- Create `services/discovery-api/app/training/__init__.py`.
- Create `services/discovery-api/app/training/examples.py`.
- Create `services/discovery-api/tests/test_training_examples.py`.

## Requirements

- Require valid impression lineage and as-of feature snapshots.
- Produce strict versioned examples with explicit exposure/label semantics,
  missingness, cohort, and synthetic markers.
- Reject future feature/event joins, duplicate IDs, cross-tenant records, and
  unbounded payloads. Emit stable manifest/checksum and time-aware splits.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_training_examples.py -q
ruff check services/discovery-api/app/training services/discovery-api/tests/test_training_examples.py
git diff --check
```

## Commit

```text
feat(discovery): add point-in-time training examples
```
