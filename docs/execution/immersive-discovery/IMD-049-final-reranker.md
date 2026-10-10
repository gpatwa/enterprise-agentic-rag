# IMD-049: Final Safety, Diversity, Freshness, and Creator Reranker

## Objective

Add the final list-level reranker. Ineligible content must never appear;
diversity, freshness, repetition, and creator-exposure constraints use a
deterministic relaxation order with explicit evidence.

## Dependencies and Reads

- IMD-029 and IMD-048 are merged. Read eligibility compiler, utility policy,
  candidate contracts, and ranking contracts.

## Owned Files

- Create `services/discovery-api/app/ranking/final_rerank.py`.
- Create `services/discovery-api/tests/test_final_reranker.py`.

## Requirements

- Apply hard safety/eligibility first, then deterministic diversity, freshness,
  repetition, and creator caps with bounded list size.
- Define and test relaxation order for infeasible constraints; never relax hard
  eligibility or blocked/safety rules.
- Preserve source/reason evidence, model/policy versions, stable ties, and
  redacted explanations. No private profile values.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_final_reranker.py -q
ruff check services/discovery-api/app/ranking/final_rerank.py services/discovery-api/tests/test_final_reranker.py
git diff --check
```

## Commit

```text
feat(discovery): add final safety diversity reranker
```
