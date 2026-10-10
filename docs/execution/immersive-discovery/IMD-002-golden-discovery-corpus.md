# IMD-002: Golden Immersive Discovery Corpus

## Objective

Create a small, deterministic, fictional corpus for immersive search,
recommendation, ranking, diversity, cold-start, and policy evaluation. This
task defines test truth only; it does not implement a generator, service,
retriever, ranker, model, or UI.

## Dependencies

None. This task may run concurrently with IMD-001.

## Read First

1. `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`
2. `services/api/tests/fixtures/search/README.md`
3. `services/api/tests/fixtures/search/documents.json`
4. `services/api/tests/fixtures/search/queries.json`
5. `services/api/tests/fixtures/search/judgments.json`
6. `services/api/tests/test_search_golden_fixtures.py`

Do not read unrelated repository files.

## Owned Files

- Create `services/discovery-api/tests/fixtures/golden/README.md`.
- Create `services/discovery-api/tests/fixtures/golden/experiences.json`.
- Create `services/discovery-api/tests/fixtures/golden/users.json`.
- Create `services/discovery-api/tests/fixtures/golden/relationships.json`.
- Create `services/discovery-api/tests/fixtures/golden/queries.json`.
- Create `services/discovery-api/tests/fixtures/golden/judgments.json`.
- Create `services/discovery-api/tests/fixtures/golden/policy_cases.json`.
- Create `services/discovery-api/tests/test_golden_fixtures.py`.

This packet explicitly allows eight created files because the fixture types
must remain independently inspectable. Do not edit production code.

## Fixture Requirements

Use stable fictional IDs and deterministic JSON. Include at least:

- 48 experiences across multiple creators, genres, themes, devices, locales,
  age ratings, freshness bands, quality bands, and popularity bands;
- 24 fictional users, including explicit-preference, short-history,
  long-history, social, multilingual, device-constrained, and cold-start
  personas;
- consented friend/group relationships with no real names or identifiers;
- 30 search queries with graded relevance judgments;
- policy cases for age, safety, locale, device, unavailable content, blocked
  items, creator repetition, and cross-tenant isolation.

The query set must cover:

- exact experience ID and exact title;
- exact phrase, typo, alias, and punctuation-sensitive term;
- genre/theme and gameplay-mechanic intent;
- natural-language semantic discovery;
- multilingual intent represented with ASCII-safe fixture values where
  practical;
- device, locale, age, and availability constraints;
- friend/co-play and item-to-item relevance;
- new-user and new-item cold start;
- stale/popular versus fresh/high-quality tradeoffs;
- diverse-result intent and near-duplicate suppression;
- an intentionally attractive but ineligible item;
- a cross-tenant near match;
- a query with no relevant result.

## Judgment and Policy Rules

- Relevance grades are integers `0`, `1`, `2`, and `3`.
- Grade `3` is directly satisfying; `2` strongly relevant; `1` weak context;
  `0` irrelevant or ineligible.
- Ineligible items remain grade `0` for the scoped persona even when semantic
  similarity is high.
- Judgments distinguish query relevance from personalization preference.
- Expected lists should express required/forbidden IDs and properties rather
  than one brittle total ordering unless exact order is the behavior under test.
- Fixtures must label all records `synthetic` and contain no copied Roblox
  titles, descriptions, imagery, usernames, or identifiers.

## Acceptance Evidence

- JSON parses without custom preprocessing and all IDs are unique.
- Every reference resolves and every experience creator/user relationship is
  valid.
- Minimum fixture counts and every required query/policy category are present.
- Both positive and no-result/cold-start cases exist.
- Cross-tenant and ineligible items are never judged retrievable for the scoped
  user.
- The loader test validates referential integrity, counts, enum vocabulary,
  synthetic markers, and deterministic ordering.
- The focused test and `git diff --check` pass.

## Stop Conditions

Stop and report instead of changing production contracts if:

- a discovery fixture corpus already exists; report its path and schema gaps;
- a required field would force IMD-003, IMD-004, or IMD-005 production-schema
  decisions. Use neutral fixture vocabulary instead.

## Targeted Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_golden_fixtures.py -q
git diff --check
```

## Commit

```text
test(discovery): IMD-002 add golden discovery corpus
```
