# IMD-037: Candidate Orchestration, Quotas, and Degradation

## Objective

Run candidate sources in bounded parallel/isolated execution, apply source
quotas and global caps, fuse results, and degrade when a source times out or
fails. Hard eligibility filters and caps must hold after fusion.

## Dependencies and Reads

- IMD-027, IMD-029, and IMD-031 through IMD-036 are merged.
- Read candidate contracts, fusion, policy compiler, and all candidate source
  modules.

## Owned Files

- Create `services/discovery-api/app/candidates/orchestrator.py`.
- Create `services/discovery-api/tests/test_candidate_orchestration.py`.

## Requirements

- Define a bounded source execution protocol with per-source timeout, result
  cap, quota, and deterministic source order.
- Isolate failures/timeouts; healthy sources continue and evidence records
  degradation without raw provider payloads.
- Recheck tenant/eligibility at the global boundary, deduplicate, enforce source
  and global caps, and return a stable candidate trace.
- No API routes, live provider calls, or model dependencies.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_candidate_orchestration.py -q
ruff check services/discovery-api/app/candidates/orchestrator.py services/discovery-api/tests/test_candidate_orchestration.py
git diff --check
```

## Commit

```text
feat(discovery): add candidate orchestration
```
