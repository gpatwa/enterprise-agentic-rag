# IMD-033: Co-Play and Co-Engagement Graph Candidates

## Objective

Add a deterministic graph candidate source from qualified interaction events.
Use time decay and support thresholds, prevent future leakage, scope by tenant,
and emit redacted reason evidence.

## Dependencies and Reads

- IMD-015, IMD-018, and IMD-030 are merged.

## Owned Files

- Create `services/discovery-api/app/candidates/social_graph.py`.
- Create `services/discovery-api/tests/test_coplay_graph.py`.

## Requirements

Only qualified/consented events contribute; enforce as-of time, minimum support,
tenant and eligibility constraints, bounded graph traversal, deterministic
decay/ties, and no private friend identity in output.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_coplay_graph.py -q
ruff check services/discovery-api/app/candidates/social_graph.py services/discovery-api/tests/test_coplay_graph.py
git diff --check
```

## Commit

```text
feat(discovery): add co-play graph candidates
```
