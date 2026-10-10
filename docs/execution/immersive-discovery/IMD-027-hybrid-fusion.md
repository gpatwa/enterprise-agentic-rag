# IMD-027: Deterministic Hybrid Fusion

## Objective

Fuse exact, lexical, and vector candidate-source results using bounded RRF or
source weights. Deduplicate candidates, preserve reason codes, enforce caps,
and degrade predictably when one source fails.

## Dependencies and Reads

- IMD-025, IMD-026, and IMD-030 are merged.
- Read candidate contracts and both retrieval modules.

## Owned Files

- Create `services/discovery-api/app/search/fusion.py`.
- Create `services/discovery-api/tests/test_hybrid_fusion.py`.

## Requirements

- Require matching tenant/request/source versions and bounded source results.
- Support deterministic reciprocal-rank fusion and explicit source weights;
  stable ties use experience ID.
- Deduplicate while retaining source/reason evidence; hard eligibility remains
  upstream and must be rechecked at the fused boundary.
- Empty, timeout, and failure sources degrade without discarding healthy data.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_hybrid_fusion.py -q
ruff check services/discovery-api/app/search/fusion.py services/discovery-api/tests/test_hybrid_fusion.py
git diff --check
```

## Commit

```text
feat(discovery): add deterministic hybrid fusion
```
