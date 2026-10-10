# IMD-007: Discovery Evaluation Metrics

## Objective

Add backend-neutral metrics for immersive retrieval, recommendation, policy,
and ranking evaluation. Keep the functions pure and deterministic so later
providers and models can be compared against the same report contract.

## Dependencies

- IMD-002 is merged at `676897d`.
- IMD-004 is merged at `ad90e75`.
- The current branch contains the IMD-004 checkpoint.

## Read First

1. `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`
2. `docs/adr/ADR-IMD-001-immersive-discovery.md`
3. `services/discovery-api/app/domain/models.py`
4. `services/discovery-api/tests/fixtures/golden/judgments.json`
5. `services/discovery-api/tests/fixtures/golden/queries.json`
6. `services/api/app/search/evaluation.py`
7. `docs/execution/immersive-discovery/IMD-007-evaluation-metrics.md`

Do not read unrelated repository files.

## Owned Files

- Create `services/discovery-api/app/evaluation/metrics.py`.
- Create `services/discovery-api/tests/test_evaluation_metrics.py`.

Do not edit support evaluation code, fixtures, ranking code, or shared platform
contracts.

## Metric Requirements

Implement pure typed functions for:

- Recall@K, MRR, and graded nDCG@K using stable deduplication;
- catalog coverage and unique-creator coverage;
- intra-list diversity using genres/themes and a deterministic zero-vector-safe
  fallback for later embedding integration;
- calibration error for predicted probabilities and observed binary outcomes;
- negative-feedback rate;
- eligibility/policy violation rate;
- a deterministic aggregate report with query count, cohort labels, metric
  versions, and explicit empty-input behavior.

Reject invalid K, non-finite probabilities/scores, duplicate metric IDs, and
ambiguous denominator cases. Define and test behavior for no judgments, no
retrieved results, all-ineligible results, duplicate candidates, and empty
lists. Do not import NumPy, sklearn, OpenSearch, or an LLM dependency.

## Acceptance Evidence

- Hand-worked cases match expected Recall@K, MRR, nDCG, coverage, diversity,
  calibration, negative-feedback, and violation values.
- Duplicate candidates do not inflate recall or coverage.
- Empty/no-judgment cases return documented deterministic values.
- Report serialization is stable and includes metric/version identifiers.
- Non-finite and invalid inputs fail clearly.
- Focused tests and `git diff --check` pass without external services.

## Targeted Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_evaluation_metrics.py -q
git diff --check
```

## Stop Conditions

Stop if a metric requires a learned model, a provider payload, a new database
schema, or an unapproved judgment policy. Record the gap for a later packet.

## Commit

```text
feat(discovery): IMD-007 add evaluation metrics
```

