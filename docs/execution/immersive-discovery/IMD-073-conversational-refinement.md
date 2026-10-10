# IMD-073: Conversational Discovery Refinement

Status: complete

## Scope

Add a local-only refinement state machine on top of the IMD-070 structured
intent and IMD-071 bounded adapter. It supports explicit add, remove, and
replace operations over parser-allowlisted constraints. It does not add a
route, persistence, model call, network dependency, or action execution.

## Safety contract

- Session state contains only versioned intent state and bounded refinement
  turns; raw transcript is never retained.
- Turns and query material are capped. The caller owns tenant, principal,
  eligibility, policy, and action context; the session neither stores nor
  mutates any of it.
- Every follow-up is parsed and validated by the IMD-070/071 contract. Unknown
  fields and provider failures use deterministic parsing or fail closed.
- Exact terms and caller-owned catalog IDs are preserved. Conversational text
  cannot change identity, eligibility, policy, or execute an action.
- Production search routes remain unchanged; callers can pass the resulting
  intent to the existing typed search integration in a later packet.

## Owned paths

- `services/discovery-api/app/intelligence/refinement.py`
- `services/discovery-api/tests/test_conversational_refinement.py`
- this packet and the canonical execution-plan status

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_conversational_refinement.py -q
ruff check services/discovery-api/app/intelligence/refinement.py \
  services/discovery-api/tests/test_conversational_refinement.py
git diff --check
```

## Commit

`feat(discovery): add conversational refinement`
