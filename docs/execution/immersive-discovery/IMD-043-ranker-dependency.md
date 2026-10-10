# IMD-043: Approved CPU Ranker Dependency

## Objective

Install only the CPU learned-ranker dependency approved by IMD-042, with an
exact version and local import smoke test. Do not add training, serving,
network calls, or any unapproved ML package.

## Dependencies and Reads

- IMD-042 is merged at the approved LightGBM version.
- Read the ADR, current discovery requirements, and local Python version policy.

## Owned Files

- Modify `services/discovery-api/requirements.txt` only to add the exact
  approved dependency.
- Create `services/discovery-api/tests/test_ranker_dependency.py`.

Do not edit application code, lock files outside the discovery service, model
artifacts, cloud/deployment, support, analytics, or web files.

## Requirements

- Pin exactly `lightgbm==4.5.0` as selected in IMD-042.
- Test the import/version and document that this does not enable online learned
  ranking or bypass fallback.
- If the package is unavailable in the current local environment, keep the
  smoke test skip-safe with an explicit evidence message rather than vendoring
  or downloading artifacts.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_ranker_dependency.py -q
git diff --check
```

## Commit

```text
build(discovery): add approved cpu ranker dependency
```
