# IMD-039: Source Recall, Overlap, Coverage, and Cold-Start Evaluation

## Objective

Extend the backend-neutral evaluator to attribute recall, overlap, coverage,
and cold-start quality by candidate source and cohort. Preserve versioned,
deterministic reports without provider or model dependencies.

## Dependencies and Reads

- IMD-007 and IMD-037 are merged. Read evaluation metrics, candidate traces,
  golden judgments, and the plan.

## Owned Files

- Modify `services/discovery-api/app/evaluation/metrics.py` only for the
  additive evaluator API.
- Modify `services/discovery-api/tests/test_source_evaluation.py` only.

Do not edit existing metric semantics, candidate modules, API, persistence,
support, analytics, or web files.

## Requirements

- Attribute source recall/overlap and cohort metrics without double counting.
- Include new-user/new-item/cold-start slices and stable metric versions.
- Keep empty/degraded inputs explicit and deterministic; reject ambiguous
  source/label joins.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_source_evaluation.py -q
ruff check services/discovery-api/app/evaluation/metrics.py services/discovery-api/tests/test_source_evaluation.py
git diff --check
```

## Commit

```text
feat(discovery): extend source evaluation metrics
```
