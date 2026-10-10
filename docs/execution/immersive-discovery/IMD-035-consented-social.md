# IMD-035: Consent-Aware Social Candidates

## Objective

Add a bounded social/group candidate source that uses only consented
relationships. Private identity and raw friend activity must not appear in
responses or traces.

## Dependencies and Reads

- IMD-015 and IMD-030 are merged. Read consent/event models and candidate
  contracts.

## Owned Files

- Create `services/discovery-api/app/candidates/consented_social.py`.
- Create `services/discovery-api/tests/test_consented_social.py`.

## Requirements

Require explicit consent, tenant/request scope, as-of time, bounded group
membership, stable hashed evidence, hard eligibility filters, deterministic
ordering, and a no-social-data fallback.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_consented_social.py -q
ruff check services/discovery-api/app/candidates/consented_social.py services/discovery-api/tests/test_consented_social.py
git diff --check
```

## Commit

```text
feat(discovery): add consent-aware social candidates
```
