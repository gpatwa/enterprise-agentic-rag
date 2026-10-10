# IMD-025: Scoped Exact and BM25 Retrieval

## Objective

Implement deterministic provider-neutral exact and lexical retrieval over
mapped catalog documents. Preserve hard tenant/eligibility filters, exact ID
precedence, title/phrase boosts, stable pagination, evidence, and no-result
behavior. Do not connect to OpenSearch; a local in-memory provider is enough.

## Dependencies and Reads

- IMD-006, IMD-021, and IMD-022 are merged.
- Read mapping/mapper contracts, domain eligibility, candidate contracts, and
  the IMD-020 ADR.

## Owned Files

- Create `services/discovery-api/app/search/lexical.py`.
- Create `services/discovery-api/tests/test_lexical_retrieval.py`.

Do not edit mapping/mapper, candidates, ranking, API, persistence, deployment,
support, analytics, or web files.

## Requirements

- Keep exact stable IDs on a keyword path before analyzed text.
- Implement deterministic BM25-like term scoring with title/tag/phrase boosts,
  bounded query normalization, stable ties, and page limits.
- Apply tenant, locale, device, age, safety, availability, and blocked filters
  before scoring; query text cannot override eligibility.
- Return candidate-source-compatible evidence with matched fields and reason
  codes, never raw private profile data.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_lexical_retrieval.py -q
ruff check services/discovery-api/app/search/lexical.py services/discovery-api/tests/test_lexical_retrieval.py
git diff --check
```

## Commit

```text
feat(discovery): add scoped lexical retrieval
```
