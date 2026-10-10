# IMD-040: Online Ranking Feature and Prediction Contracts

## Objective

Freeze strict provider-neutral user/item/context/cross-feature and prediction
contracts for online ranking. Define missingness, objectives, and versions
without selecting a learned model or adding serving behavior.

## Dependencies and Reads

- IMD-038 is merged. Read feature hydration, domain contracts, candidate
  contracts, and the plan.

## Owned Files

- Create `services/discovery-api/app/ranking/__init__.py`.
- Create `services/discovery-api/app/ranking/contracts.py`.
- Create `services/discovery-api/tests/test_ranking_contracts.py`.

## Requirements

- Model immutable versioned user/item/context/cross features with typed values,
  explicit missingness, finite bounds, and no private/raw history fields.
- Model prediction outputs with candidate identity, stage/version, score,
  uncertainty/missingness, and a redacted reason surface.
- Reject unknown fields, mixed versions, NaN/inf, unbounded feature maps, and
  predictions for candidates outside the supplied batch.
- Keep eligibility/policy separate from model score.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_ranking_contracts.py -q
ruff check services/discovery-api/app/ranking services/discovery-api/tests/test_ranking_contracts.py
git diff --check
```

## Commit

```text
feat(discovery): freeze ranking contracts
```
