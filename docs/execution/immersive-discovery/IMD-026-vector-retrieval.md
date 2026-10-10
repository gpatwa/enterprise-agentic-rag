# IMD-026: Filtered Vector Retrieval

## Objective

Implement a deterministic provider-neutral vector retrieval contract and local
fake provider. ANN request construction must apply hard eligibility filters
before scoring and return only known items with matching versioned vectors.
Do not connect to OpenSearch or call an embedding model.

## Dependencies and Reads

- IMD-006, IMD-020, and IMD-022 are merged.
- Read the mapping/mapper contracts, domain eligibility, candidate contracts,
  and IMD-020 vector strategy.

## Owned Files

- Create `services/discovery-api/app/search/vector.py`.
- Create `services/discovery-api/tests/test_vector_retrieval.py`.

Do not edit mapping/mapper, lexical retrieval, candidates, ranking, API,
persistence, deployment, support, analytics, or web files.

## Requirements

- Require explicit embedding model/version, dimensions, and cosine contract.
- Validate finite query/document vectors and reject mixed dimensions/versions.
- Apply tenant, locale, device, age, safety, availability, and blocked filters
  before similarity scoring; use deterministic cosine similarity and ties.
- Bound k/candidate counts and return reason/evidence metadata compatible with
  candidate contracts. Missing provider/vector data degrades explicitly.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_vector_retrieval.py -q
ruff check services/discovery-api/app/search/vector.py services/discovery-api/tests/test_vector_retrieval.py
git diff --check
```

## Commit

```text
feat(discovery): add filtered vector retrieval
```
