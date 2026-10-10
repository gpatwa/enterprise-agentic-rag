# IMD-036: User and Item Cold-Start Policy

## Objective

Add deterministic cold-start policy for new users and items. Use explicit
contextual priors and bounded exploration only after safety/quality gates.

## Dependencies and Reads

- IMD-014, IMD-018, and IMD-030 are merged.

## Owned Files

- Create `services/discovery-api/app/candidates/cold_start.py`.
- Create `services/discovery-api/tests/test_cold_start.py`.

## Requirements

Distinguish no-history/new-user and new-item states, apply tenant/locale/device/
age/safety/availability/quality filters, cap exploration and creator exposure,
use seed-stable ordering, and emit explicit cold-start reasons. No hidden
personal data or model calls.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_cold_start.py -q
ruff check services/discovery-api/app/candidates/cold_start.py services/discovery-api/tests/test_cold_start.py
git diff --check
```

## Commit

```text
feat(discovery): add cold start policy
```
