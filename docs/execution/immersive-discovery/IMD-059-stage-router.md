# IMD-059: Stage Router, Reason Codes, Redaction, and Fallback Chain

## Objective

Route requests through hybrid-only, pre-rank, learned-rank, and full-rank modes
predictably. Record redacted reason codes and execute a complete deterministic
fallback chain without changing hard eligibility.

## Dependencies and Reads

- IMD-044 and IMD-047 through IMD-049 are merged. Read ranking contracts,
  inference, utility, final reranker, candidate orchestration, and policy.

## Owned Files

- Create `services/discovery-api/app/ranking/router.py`.
- Create `services/discovery-api/tests/test_stage_router.py`.

## Requirements

- Define explicit modes, ordered stages, per-stage caps/timeouts, fallback
  reasons, component/policy/model versions, and redacted explanations.
- Unknown/disabled/failed/timed-out stages fall back deterministically; no stage
  may add candidates, bypass eligibility, or expose private features/model
  internals.
- Emit an immutable decision trace suitable for later audit and experiments.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_stage_router.py -q
ruff check services/discovery-api/app/ranking/router.py services/discovery-api/tests/test_stage_router.py
git diff --check
```

## Commit

```text
feat(discovery): add ranking stage router
```
