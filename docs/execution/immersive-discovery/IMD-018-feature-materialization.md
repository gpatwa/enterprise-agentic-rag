# IMD-018: Point-in-Time Feature Materialization

## Objective

Materialize versioned user, item, context, social, popularity, and retention
features from canonical records and event-lake inputs. Point-in-time tests
must prevent future leakage, and rebuilds must produce the same manifest.

## Dependencies and Reads

- IMD-013, IMD-015, and IMD-017 are merged.
- Read persistence DTOs, simulator/event-lake contracts, domain models, and
  the evaluation plan.

## Owned Files

- Create `services/discovery-api/app/features/__init__.py`.
- Create `services/discovery-api/app/features/materialization.py`.
- Create `services/discovery-api/tests/test_feature_materialization.py`.

## Requirements

- Use typed versioned feature records with explicit as-of time, source
  watermark, feature age, consent state, and synthetic marker.
- Build only from events at or before the as-of boundary; future events must
  not affect a materialized result.
- Provide deterministic user/item/context/social/popularity/retention features
  with bounded cardinality and safe defaults for missing data.
- Emit a stable manifest/checksum and support deletion-aware rebuild inputs.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_feature_materialization.py -q
ruff check services/discovery-api/app/features services/discovery-api/tests/test_feature_materialization.py
git diff --check
```

## Commit

```text
feat(discovery): add point-in-time feature materialization
```
