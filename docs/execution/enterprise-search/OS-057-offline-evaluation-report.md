# OS-057 Offline Search Evaluation Report

Corpus: `services/api/tests/fixtures/search` (24 documents, 12 queries,
versioned ACL judgments). Metrics are computed with the shared evaluator at
`services/api/app/search/evaluation.py`, `k=10`, minimum relevance grade 1.

## Reproducible procedure

1. Run the fixture integrity tests.
2. Run the lexical, vector, and hybrid providers against the same documents.
3. Record retrieved document IDs only, then run `evaluate_run`.
4. Run the ACL adversarial cases separately and require zero inaccessible IDs.

The provider-fake gate is reproducible in local CI. Live OpenSearch baseline
numbers are intentionally not fabricated: they require `OS-051` integration
execution against the started local profile and are recorded as an attached
run artifact when available. The report schema compares the legacy
Qdrant+PostgreSQL fusion baseline with OpenSearch BM25, vector, and hybrid
results without including ticket text or embeddings.

Required release thresholds: ACL leakage `0`, duplicate IDs `0`, and no
regression greater than 5% in NDCG@10 versus the approved baseline.
