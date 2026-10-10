# IMD-034: Two-Tower Retrieval Baseline

## Objective

Add a provider-neutral, deterministic two-tower retrieval baseline and offline
export contract. User/item embeddings are versioned, cold-start vectors are
deterministic, and ANN export is reproducible. Do not add neural dependencies
or online serving.

## Dependencies and Reads

- IMD-018 and IMD-030 are merged. Read feature and candidate contracts plus
  the IMD-020 vector ADR.

## Owned Files

- Create `services/discovery-api/app/retrieval/two_tower.py`.
- Create `services/discovery-api/tests/test_two_tower.py`.

## Requirements

Use a documented deterministic CPU baseline with explicit model/version,
dimensions, finite values, stable export checksum, and cold-start behavior.
Keep user vectors out of ordinary logs and do not call a live model.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_two_tower.py -q
ruff check services/discovery-api/app/retrieval/two_tower.py services/discovery-api/tests/test_two_tower.py
git diff --check
```

## Commit

```text
feat(discovery): add two tower retrieval baseline
```
