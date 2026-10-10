# IMD-015: Exposure-Aware Behavior and Social-Graph Simulator

## Objective

Add a deterministic fictional behavior simulator that only emits actions with
valid impression lineage. It should respond to affinity and context, generate
retention/co-play signals, and never use future state or real identities.

## Dependencies and Reads

- IMD-005 and IMD-014 are merged.
- Read event models, generated catalog APIs, golden fixtures, and the plan.

## Owned Files

- Create `services/discovery-api/app/simulation/__init__.py`.
- Create `services/discovery-api/app/simulation/behavior.py`.
- Create `services/discovery-api/tests/test_behavior_simulator.py`.

Do not edit events, generator, persistence, search, API, deployment, support,
analytics, or web files.

## Requirements

- Use an explicit seed and bounded profile; same inputs produce identical
  ordered events.
- Emit typed interaction events with matching tenant/user/request/impression
  lineage and synthetic markers.
- Model affinity/context effects through documented deterministic rules,
  including qualified play, return, retention, and co-play where applicable.
- Prevent future leakage: event decisions may use only prior event state.
- Keep graph identities synthetic and outputs bounded.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_behavior_simulator.py -q
ruff check services/discovery-api/app/simulation services/discovery-api/tests/test_behavior_simulator.py
git diff --check
```

## Commit

```text
feat(discovery): add exposure-aware behavior simulator
```
