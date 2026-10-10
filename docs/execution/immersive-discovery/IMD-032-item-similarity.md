# IMD-032: Item-to-Item Similarity Candidates

## Objective

Add deterministic item-to-item candidates using approved metadata and/or
versioned vectors. Exclude the seed and blocked items, enforce tenant and
eligibility filters, bound results, and record reason codes.

## Dependencies and Reads

- IMD-026 and IMD-030 are merged. Read vector retrieval and candidate
  contracts.

## Owned Files

- Create `services/discovery-api/app/candidates/similar.py`.
- Create `services/discovery-api/tests/test_item_similarity.py`.

## Requirements

Use only approved genres/themes/mechanics or matching vector contract; reject
mixed versions, apply hard eligibility before score, exclude seed/duplicates,
and use deterministic ties. No external service.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_item_similarity.py -q
ruff check services/discovery-api/app/candidates/similar.py services/discovery-api/tests/test_item_similarity.py
git diff --check
```

## Commit

```text
feat(discovery): add item similarity candidates
```
