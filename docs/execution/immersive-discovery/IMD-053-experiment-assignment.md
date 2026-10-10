# IMD-053: Deterministic Experiment Assignment and Exposure Logging

## Objective

Assign users deterministically to mutually exclusive experiment variants and
record exposure with all component versions, excluding raw histories.

## Dependencies and Reads

- IMD-003 and IMD-050 are merged.

## Owned Files

- Create `services/discovery-api/app/experiments/assignment.py`.
- Create `services/discovery-api/tests/test_experiment_assignment.py`.

## Requirements

- Use a versioned stable hash of tenant/user/experiment identity; bound variant
  count and ensure assignment remains stable across requests.
- Enforce tenant scope, consent, allowlisted experiment configuration, and
  mutually exclusive variants.
- Emit immutable redacted exposure records containing assignment and component
  versions, not raw query/history/profile data.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_experiment_assignment.py -q
ruff check services/discovery-api/app/experiments/assignment.py services/discovery-api/tests/test_experiment_assignment.py
git diff --check
```

## Commit

```text
feat(discovery): add deterministic experiment assignment
```
