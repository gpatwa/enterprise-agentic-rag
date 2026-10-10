# IMD-056: Consent Withdrawal, Retention, Export, and Deletion

## Objective

Implement a local privacy workflow that locates canonical and derived records,
deletes or tombstones them, prevents reappearance after rebuild, and provides
bounded export evidence.

## Dependencies and Reads

- IMD-013, IMD-017, and IMD-051 are merged.

## Owned Files

- Create `services/discovery-api/app/privacy/workflow.py`.
- Create `services/discovery-api/tests/test_privacy_workflow.py`.

## Requirements

- Require tenant/user scope, consent state, explicit operation, retention
  policy, and bounded confirmation token.
- Cover canonical catalog/profile/events, event lake partitions, features,
  profile data, model inputs, and derived index tombstones without restoring
  deleted content.
- Export only approved fields, redact sensitive values, and emit append-only
  evidence with checksums/status. No cloud/third-party deletion calls.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_privacy_workflow.py -q
ruff check services/discovery-api/app/privacy services/discovery-api/tests/test_privacy_workflow.py
git diff --check
```

## Commit

```text
feat(discovery): add privacy workflow
```
