# IMD-045: Repeatable Offline Ranker Training

## Objective

Add a local training command that uses IMD-041 examples and the approved CPU
ranker when available. Fixed seeds must produce recorded dataset/features/
metrics/artifact checksums; the split is time-aware. Model training is offline
only and must have a deterministic fallback when LightGBM is unavailable.

## Dependencies and Reads

- IMD-041, IMD-042, IMD-043 are merged.

## Owned Files

- Create `services/discovery-api/app/training/ranker.py`.
- Create `services/discovery-api/tests/test_ranker_training.py`.

## Requirements

- Validate dataset and feature versions, seed, time split, bounded rows, and
  finite values.
- Produce a redacted artifact manifest with checksums, metrics, versions, and
  fallback status; never log raw profiles or vectors.
- Use LightGBM only through an optional import; deterministic linear fallback
  remains available and clearly labeled.
- No online serving, model download, or cloud storage.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_ranker_training.py -q
ruff check services/discovery-api/app/training/ranker.py services/discovery-api/tests/test_ranker_training.py
git diff --check
```

## Commit

```text
feat(discovery): add repeatable offline ranker training
```
