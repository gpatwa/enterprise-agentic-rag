# IMD-029: Fail-Closed Eligibility Filter Compiler

## Objective

Compile typed request and user context into provider-neutral eligibility
predicates. Age, safety, locale, device, availability, tenant, consent, and
blocked-item constraints must be hard filters that no query or score can
override.

## Dependencies and Reads

- IMD-004 and IMD-021 are merged.
- Read domain eligibility, mapping fields, query constraints, and the plan.

## Owned Files

- Create `services/discovery-api/app/policy/__init__.py`.
- Create `services/discovery-api/app/policy/eligibility.py`.
- Create `services/discovery-api/tests/test_eligibility_filter.py`.

## Requirements

- Produce a typed, serializable filter expression and deterministic decision
  reasons; missing required context fails closed.
- Keep tenant, age, safety, locale, device, availability, consent,
  personalization, and blocked IDs explicit and independently testable.
- Reject unknown fields/values and never include model scores or private profile
  attributes in the compiled expression.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_eligibility_filter.py -q
ruff check services/discovery-api/app/policy services/discovery-api/tests/test_eligibility_filter.py
git diff --check
```

## Commit

```text
feat(discovery): add fail-closed eligibility compiler
```
