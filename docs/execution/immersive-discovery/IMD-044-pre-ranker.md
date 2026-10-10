# IMD-044: Deterministic Pre-Ranker

## Objective

Add a cheap bounded pre-ranker over candidates and frozen ranking features.
It reduces the candidate set without changing eligibility and has an explicit
no-history fallback.

## Dependencies and Reads

- IMD-037 and IMD-040 are merged.

## Owned Files

- Create `services/discovery-api/app/ranking/pre_rank.py`.
- Create `services/discovery-api/tests/test_pre_rank.py`.

## Requirements

- Use a deterministic versioned weighted score over allowlisted features only.
- Preserve candidate identity/source/reason evidence, hard eligibility, caps,
  stable ties, and no-history defaults.
- Reject mixed versions, NaN/inf, unknown features, and candidates outside the
  supplied batch. Do not add learned dependencies.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_pre_rank.py -q
ruff check services/discovery-api/app/ranking/pre_rank.py services/discovery-api/tests/test_pre_rank.py
git diff --check
```

## Commit

```text
feat(discovery): add deterministic pre-ranker
```
