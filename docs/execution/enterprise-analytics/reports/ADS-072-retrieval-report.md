# ADS-072: Context and Ontology Retrieval, Provenance, Freshness, and Token Efficiency

Suite `m7-retrieval-v1`, corpus `e1f69faf3609`. **Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED; a pass is not a go/no-go.

## Scope and limits

- Indexed through the real `OpenSearchContextIndex` adapter into an in-memory stand-in that scores by term overlap and applies the adapter's filters. It is not BM25 and has no analyzers or embeddings.
- 40 hand-written queries over a 12-dataset catalogue with lookalike, uncertified, stale, and other-tenant distractors.
- Token baseline is sending the whole certified catalogue (308 estimated tokens); mean bounded pack is 68.

## Metrics

| Metric | Measured | Gate | Meets | Plan gate |
|---|---:|---:|:---:|---|
| `certified_top3_recall` | 1 | >= 0.98 | yes | Certified dataset/metric top-3 recall >= 98% |
| `uncertified_or_foreign_results` | 0 | <= 0 | yes | Uncertified or other-tenant results served: 0 (provider-owned filters) |
| `provenance_coverage` | 1 | >= 1.0 | yes | Provenance on every served asset: 100% |
| `stale_detection_recall` | 1 | >= 1.0 | yes | Stale assets detected by the freshness gate: 100% |
| `context_token_reduction` | 0.7805 | >= 0.2 | yes | Context tokens per successful intent: baseline -20% |
| `pack_budget_overruns` | 0 | <= 0 | yes | Packs over their token budget: 0 |

## Misses

None.

## Not measured

- **real_relevance_ranking**: the stand-in is term overlap, not BM25, analyzers, or embeddings; recall on a real OpenSearch index and a real catalogue size is untested
- **paraphrase_robustness**: queries are written against the catalogue's vocabulary and aliases; unseen customer wording is not measured
- **live_index**: no live OpenSearch validation was run (requires the user's explicit request)
- **baseline**: the token baseline is the whole certified catalogue, not the ADS-007 v1 baseline
