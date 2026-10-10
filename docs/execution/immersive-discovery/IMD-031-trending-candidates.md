# IMD-031: Trending, Quality, and Freshness Candidates

## Objective

Add a deterministic candidate source using versioned popularity, quality, and
freshness features. Apply time decay, minimum quality, small-item
normalization, stable ties, tenant scope, and source caps.

## Dependencies and Reads

- IMD-018 and IMD-030 are merged. Read feature materialization and candidate
  contracts.

## Owned Files

- Create `services/discovery-api/app/candidates/trending.py`.
- Create `services/discovery-api/tests/test_trending_candidates.py`.

## Requirements

Use only as-of feature values; reject stale/version-mismatched inputs, apply
quality/safety/eligibility boundaries, bound output, and emit stable reason
codes. No provider calls or LLMs.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_trending_candidates.py -q
ruff check services/discovery-api/app/candidates/trending.py services/discovery-api/tests/test_trending_candidates.py
git diff --check
```

## Commit

```text
feat(discovery): add trending candidate source
```
