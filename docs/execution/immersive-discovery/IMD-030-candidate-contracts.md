# IMD-030: Candidate-Source Contracts and Trace

## Objective

Define typed candidate-source outputs, source quotas, and candidate trace
contracts. Outputs must be bounded, versioned, tenant-scoped, eligible, and
independently degradable. This is a contract task; do not implement source
algorithms, orchestration, retrieval, ranking, or API routes.

## Dependencies and Reads

- IMD-003, IMD-004, and IMD-006 are merged.
- Read shared discovery contracts, domain models, fakes, and the execution
  plan.

## Owned Files

- Create `services/discovery-api/app/candidates/__init__.py`.
- Create `services/discovery-api/app/candidates/contracts.py`.
- Create `services/discovery-api/tests/test_candidate_contracts.py`.

Do not edit fakes, domain models, search, ranking, persistence, API,
deployment, support, analytics, or web files.

## Requirements

- Model source identity/version, candidate IDs, bounded scores/signals, reason
  codes, eligibility evidence, quotas, and degradation status.
- Enforce tenant/request identity, unique candidates, stable ordering, caps,
  finite scores, and no private/raw profile data.
- Represent timeout/failure/empty source results without failing the whole
  request and keep trace data redacted and deterministic.
- Keep source contracts provider-neutral and compatible with later lexical,
  vector, social, cold-start, and ranker implementations.

## Acceptance and Validation

Tests cover valid source results, cap/duplicate/tenant/version rejection,
reason-code and degradation serialization, deterministic traces, and strict
extra-field rejection.

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
pytest services/discovery-api/tests/test_candidate_contracts.py -q
ruff check services/discovery-api/app/candidates services/discovery-api/tests/test_candidate_contracts.py
git diff --check
```

## Commit

```text
feat(discovery): define candidate source contracts
```
