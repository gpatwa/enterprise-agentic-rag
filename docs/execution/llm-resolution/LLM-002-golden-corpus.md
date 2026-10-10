# LLM-002: Adversarial Resolution Golden Corpus

## Objective

Create a small, deterministic support-resolution corpus that can evaluate
intent extraction, multi-query planning, evidence selection, grounded claims,
abstention, and safe action proposals without a live model.

## Dependencies

None. This task may run concurrently with LLM-001.

## Read First

1. `docs/LLM_RESOLUTION_INTELLIGENCE_EXECUTION_PLAN.md`
2. `services/api/tests/fixtures/search/README.md`
3. `services/api/tests/fixtures/search/documents.json`
4. `services/api/tests/fixtures/search/queries.json`
5. `services/api/tests/fixtures/search/judgments.json`
6. `services/api/tests/test_search_golden_fixtures.py`
7. `services/api/tests/test_support_resolver.py`

Do not read unrelated repository files.

## Owned Files

- Create `services/api/tests/fixtures/llm_resolution/README.md`.
- Create `services/api/tests/fixtures/llm_resolution/cases.json`.
- Create `services/api/tests/test_llm_resolution_golden_fixtures.py`.

Do not edit production code or the existing enterprise-search corpus.

## Fixture Shape

Each case must contain stable identifiers and JSON-only fields for:

- ticket text and metadata;
- authorized evidence labels and source IDs;
- expected intent, entities, constraints, and exact terms;
- acceptable query concepts, not one brittle generated sentence;
- supported claims and forbidden claims;
- expected confidence band and abstention decision;
- allowed action types and minimum approval/risk level;
- tags identifying adversarial properties.

## Required Cases

Include at least twelve cases covering:

1. exact error code and known solved ticket;
2. vague symptom requiring semantic retrieval;
3. product/version constraint;
4. conflicting historical resolutions;
5. stale evidence superseded by a newer article;
6. weak evidence requiring abstention;
7. prompt injection inside ticket text;
8. prompt injection inside retrieved evidence;
9. fabricated or unknown citation;
10. cross-tenant evidence ID that must remain unauthorized;
11. unsafe/destructive action request requiring denial;
12. valid low-risk draft command requiring human approval.

Reuse document IDs from the search corpus where practical. Do not copy large
document bodies; reference stable IDs and include only the minimal snippets
needed by the case.

## Acceptance Evidence

- JSON parses and all IDs are unique.
- Every case has at least one tag and a complete expected-outcome block.
- Both positive and abstention cases exist.
- Prompt-injection text remains fixture data and is visibly labeled unsafe.
- Cross-tenant evidence is never listed as authorized evidence.
- The focused fixture validation test passes.
- `git diff --check` passes.

## Stop Conditions

Stop and report instead of changing production contracts if:

- the existing search fixture IDs are unstable or unavailable;
- a required expected field cannot be represented without deciding LLM-003 or
  LLM-004 schema details. Use neutral fixture vocabulary rather than inventing
  production classes.

## Targeted Validation

```bash
PYTHONPATH="$PWD/services/api:$PWD" pytest services/api/tests/test_llm_resolution_golden_fixtures.py -q
git diff --check
```

## Commit

```text
test(resolution): LLM-002 add adversarial golden corpus
```

