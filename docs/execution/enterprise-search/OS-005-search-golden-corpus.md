# OS-005: Search Golden Corpus and Judgments

## Objective

Create a deterministic, backend-neutral support-search corpus that later tasks
can use to compare Python lexical plus Qdrant against OpenSearch. This task
defines data and expected relevance judgments only; it does not implement a
search backend or evaluator.

## Dependencies

None.

## Owned Files

- Create files under `services/api/tests/fixtures/search/` only.
- A small fixture-loading test may be added as
  `services/api/tests/test_search_golden_fixtures.py`.
- Do not edit support production code.

## Required Fixture Files

- `documents.json`: canonical searchable documents.
- `queries.json`: stable query IDs and text.
- `judgments.json`: query/document relevance grades.
- `README.md`: schema, invariants, and extension rules.

## Corpus Requirements

Include at least 24 documents across two tenants. Cover tickets, comments, and
articles with stable IDs. Include these retrieval cases:

- Exact ticket ID.
- Exact error code and punctuation-sensitive error text.
- Product, plan, and feature names.
- Exact phrase in title and exact phrase in body.
- Synonym or paraphrase requiring semantic retrieval.
- Related issue with no shared important terms.
- Status, provider, source type, and time filters.
- Duplicate or near-duplicate content.
- Stale versus current guidance.
- Public, group-restricted, user-restricted, and inaccessible documents.
- An intentionally similar document in the other tenant.
- A query with no relevant result.

Use fictional data and no customer or production content.

## Judgment Rules

- Use integer grades `0`, `1`, `2`, and `3`.
- Grade `3` means direct resolution evidence.
- Grade `2` means strongly relevant supporting evidence.
- Grade `1` means weak context.
- Grade `0` means irrelevant or inaccessible.
- ACL-inaccessible documents must never be considered retrievable even when
  their semantic relevance is high.

## Acceptance Evidence

- JSON parses without custom preprocessing.
- All document, query, and judgment references are valid and unique.
- Both tenants and every required retrieval case are represented.
- The loader test checks referential integrity and fixture counts.
- The fixture files are deterministic and contain no timestamps generated at
  test runtime.

## Validation

```bash
PYTHONPATH="$PWD/services/api:$PWD" \
  pytest services/api/tests/test_search_golden_fixtures.py -q
git diff --check
```

## Stop Conditions

Stop if an existing golden search corpus is discovered. Report its path and the
schema differences rather than creating a competing fixture format.

## Commit

```text
test(search): OS-005 add golden retrieval corpus
```
