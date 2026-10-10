# IMD-070: Structured Discovery-Intent Contract

## Objective

Define a strict, deterministic contract for optional local intelligence to add
bounded query expansions without changing parser-owned meaning, request
identity, eligibility, safety, or authoritative catalog facts.

## Dependencies and Reads

- IMD-028 deterministic query and context contracts are merged.
- Read `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md` and
  `services/discovery-api/app/query/parser.py`.

## Owned Files

- `services/discovery-api/app/intelligence/__init__.py`
- `services/discovery-api/app/intelligence/intent.py`
- `services/discovery-api/tests/test_intent_contract.py`

No route wiring, provider SDK, support code, analytics code, or deployment
configuration is in scope.

## Requirements

- Use frozen Pydantic models with forbidden extra fields and strict validation.
- Preserve exact terms, parser lexical text, empty/no-result semantics,
  allowlisted constraints, and caller-supplied explicit catalog IDs.
- Cap expansions at eight entries and 64 characters per entry, with a 512
  character aggregate bound. Deduplicate expansion strings deterministically.
- Keep tenant, user identity, safety, eligibility, and authoritative catalog
  fields out of the contract so optional intelligence cannot mutate them.
- Treat injection-like text as ordinary data; provide no executable or prompt
  fields and make no provider or network calls.
- Expose a deterministic builder on top of `parse_query` for future adapters.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_intent_contract.py -q
ruff check services/discovery-api/app/intelligence services/discovery-api/tests/test_intent_contract.py
git diff --check
```

## Stop Conditions

- Do not add a production route or call a live model.
- Do not add fields for tenant, user, safety, eligibility, or catalog authority.
- Stop if implementation requires changes outside the owned paths.

## Commit

```text
feat(discovery): add structured intent contract
```
