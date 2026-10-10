# IMD-046: Local Immutable Model Registry

## Objective

Add a local model registry with draft/candidate/approved/deprecated lifecycle,
compatibility checks, and rollback. Artifacts are represented by checksums and
metadata; do not add cloud registry or serving.

## Dependencies and Reads

- IMD-045 is merged. Read training manifests, ranking contracts, and the
  trust/audit rules in the canonical plan.

## Owned Files

- Create `services/discovery-api/app/ranking/registry.py`.
- Create `services/discovery-api/tests/test_model_registry.py`.

## Requirements

- Use immutable versioned records with artifact/dataset/feature/policy
  compatibility metadata and explicit lifecycle transitions.
- Reject checksum/version mismatch, invalid transitions, duplicate versions,
  and promotion without required evidence.
- Support deterministic promotion, deprecation, active-version lookup, and
  rollback with append-only audit evidence and no secret/raw artifact data.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_model_registry.py -q
ruff check services/discovery-api/app/ranking/registry.py services/discovery-api/tests/test_model_registry.py
git diff --check
```

## Commit

```text
feat(discovery): add local model registry
```
