# IMD-048: Reviewed Multi-Objective Utility Policy

## Objective

Combine qualified play, satisfaction, return, save, and negative signals using
versioned weights and caps. Keep policy explicit, bounded, auditable, and
separate from hard eligibility.

## Dependencies and Reads

- IMD-040 and IMD-047 are merged. Read ranking contracts, inference fallback,
  event/metric semantics, and trust requirements.

## Owned Files

- Create `services/discovery-api/app/ranking/objectives.py`.
- Create `services/discovery-api/tests/test_utility_policy.py`.

## Requirements

- Define immutable objective names, weights, penalties, normalization, caps,
  and policy version; reject unknown/duplicate objectives and non-finite data.
- Make negative feedback and safety penalties bounded and unable to reintroduce
  ineligible content.
- Produce component-level redacted evidence and deterministic score/ties.
- Provide conservative defaults and explicit kill/fallback behavior.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_utility_policy.py -q
ruff check services/discovery-api/app/ranking/objectives.py services/discovery-api/tests/test_utility_policy.py
git diff --check
```

## Commit

```text
feat(discovery): add multi-objective utility policy
```
