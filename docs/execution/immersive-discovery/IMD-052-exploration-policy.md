# IMD-052: Bounded Exploration Policy

## Objective

Add deterministic exploration with explicit budget, eligibility, creator caps,
seed reproducibility, and kill switch. Exploration must never bypass safety or
policy filters.

## Dependencies and Reads

- IMD-036, IMD-049, and IMD-051 are merged.

## Owned Files

- Create `services/discovery-api/app/ranking/exploration.py`.
- Create `services/discovery-api/tests/test_exploration_policy.py`.

## Requirements

- Bound per-request/per-user budget and candidate exposure; use stable seed and
  explicit policy/version.
- Apply tenant, consent, age, safety, availability, blocked, quality, and
  creator limits before selecting exploration candidates.
- Support kill switch and deterministic fallback with redacted reason evidence.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_exploration_policy.py -q
ruff check services/discovery-api/app/ranking/exploration.py services/discovery-api/tests/test_exploration_policy.py
git diff --check
```

## Commit

```text
feat(discovery): add bounded exploration policy
```
