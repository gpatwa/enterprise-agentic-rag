# IMD-028: Deterministic Query Parsing

## Objective

Add deterministic query normalization and an optional intent contract. Preserve
exact names/IDs, extract only allowlisted constraints, handle empty/noisy input,
and require no LLM.

## Dependencies and Reads

- IMD-004 and IMD-027 are merged.
- Read domain filters, candidate contracts, retrieval modules, and the plan.

## Owned Files

- Create `services/discovery-api/app/query/__init__.py`.
- Create `services/discovery-api/app/query/parser.py`.
- Create `services/discovery-api/tests/test_query_parser.py`.

## Requirements

- Bound raw query length and token count; normalize harmless whitespace/case
  while preserving exact ID/name candidates.
- Extract only allowlisted locale/device/genre/theme/age terms; invalid or
  ambiguous constraints remain absent rather than being guessed.
- Return stable query version, exact terms, lexical text, constraints, and
  no-result/empty indicators. No user profile or prompt injection content is
  executed.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_query_parser.py -q
ruff check services/discovery-api/app/query services/discovery-api/tests/test_query_parser.py
git diff --check
```

## Commit

```text
feat(discovery): add deterministic query parser
```
