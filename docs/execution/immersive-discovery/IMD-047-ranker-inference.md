# IMD-047: Bounded Online Ranker Inference and Fallback

## Objective

Add bounded online ranker inference over the approved model registry with
deterministic fallback. Unknown, incompatible, missing, or timed-out models
must fall back without adding candidates or mutating eligibility.

## Dependencies and Reads

- IMD-044 and IMD-046 are merged. Read pre-ranker, registry, ranking contracts,
  and eligibility policy.

## Owned Files

- Create `services/discovery-api/app/ranking/inference.py`.
- Create `services/discovery-api/tests/test_ranker_inference.py`.

## Requirements

- Require explicit model/feature/policy versions and candidate-batch identity.
- Bound candidate count, feature size, latency/attempts, and score range.
- Preserve hard eligibility, source/reason evidence, deterministic ties, and
  redacted fallback reason. Model failure/timeout cannot fail the whole request.
- Keep model loading local/provider-neutral; no network or secret material.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_ranker_inference.py -q
ruff check services/discovery-api/app/ranking/inference.py services/discovery-api/tests/test_ranker_inference.py
git diff --check
```

## Commit

```text
feat(discovery): add bounded ranker inference
```
