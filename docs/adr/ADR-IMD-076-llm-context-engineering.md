# ADR-IMD-076: LLM Context Engineering for Immersive Discovery

Status: Accepted for local offline and shadow evaluation only
Date: 2026-08-31

## Decision

Use a versioned, provider-neutral `DiscoveryRankingContext` as the boundary
between discovery data and any future LLM-assisted ranking experiment. The
context adapter may compact and enrich already-authorized request, user, item,
session, and candidate information. It may not create candidates, change
eligibility, or replace the deterministic policy and audit stages.

This decision has three explicit stages:

1. **Current serving:** OpenSearch retrieval, candidate fusion, CPU or approved
   learned ranking, then utility and safety policy.
2. **Near term:** bounded LLM context compaction/enrichment in offline or
   shadow mode, followed by the existing ranker and policy stages.
3. **Future experiment:** a GenRec-style context encoder with a catalog-aware
   scoring head, evaluated only after the gates below pass.

The current product remains in stages 1 and 2. Stage 3 is not enabled for
online traffic.

## Contract

Every context record carries a schema version and the versions needed to
rebuild or audit it. The logical shape is:

| Section | Required contents | Authority |
|---|---|---|
| Request | tenant, request, locale, device, session, consent, and age context | Caller and policy context |
| User | explicit preferences, bounded recent-history summary, and cold-start state | Versioned profile materialization |
| Item | catalog ID, authoritative metadata references, and derived feature references | Catalog plus feature versions |
| Candidates | closed list of retrieved catalog IDs, source lineage, and eligibility snapshot | OpenSearch and policy evaluation |
| Context metadata | schema, compaction policy, provider/model/prompt, cache, and budget metadata | Context adapter |
| Evidence | dataset, feature, embedding, ranker, policy, and experiment versions | Evaluation and audit contracts |

The context contains references and bounded summaries rather than unrestricted
raw history. Sensitive query text, raw personal history, full embeddings, and
secrets are redacted from normal audit records.

## Compaction and authority rules

- Preserve explicit user preferences, current session intent, recent positive
  and negative feedback, and cold-start signals before lower-value history.
- Collapse repetitive events into bounded counts or time-window summaries.
- Drop low-signal history deterministically when the token budget is reached;
  never silently expand the budget.
- Keep authoritative catalog, consent, age, safety, availability, and tenant
  fields outside the LLM's authority. The LLM receives them as constraints and
  cannot rewrite them.
- Candidate IDs are a closed set from retrieval. An LLM-created or unknown ID
  is rejected rather than resolved heuristically.
- On timeout, malformed output, budget exhaustion, injection detection, or
  kill switch, use the deterministic context and ranking path.

## Evaluation and promotion gates

The local evaluator must report model-off and model-on results for the same
dataset, candidate set, policy version, and experiment assignment. Promotion
requires:

- zero tenant, ACL, age, safety, availability, or candidate-membership
  violations;
- no regression against the deterministic baseline on the selected relevance
  metrics, with any claimed lift reported separately from synthetic-data
  plumbing evidence;
- configured and measured p50/p95 latency, token use, cache hit rate, and
  per-request cost within the experiment budget;
- stable reason codes and complete schema, model, context, policy, and audit
  version evidence;
- deterministic fallback coverage for provider errors and kill-switch tests;
- human review of the comparison before any online traffic exposure.

The future scoring head must score only eligible retrieved candidates and must
run before the existing final policy re-ranker, never after it. No synthetic
demo result is evidence of customer lift.

## Consequences

This creates a useful LLM integration point without coupling the product to a
provider, online model availability, GPU serving, or a vendor-specific
architecture. It adds context-version and budget bookkeeping, but those costs
are necessary for reproducible ranking experiments and trusted operations.

The pattern is informed by [Netflix's GenRec discussion](https://netflixtechblog.com/genrec-towards-llm-native-recommendation-at-netflix-f20be6f643e3),
but this repository does not claim equivalent data scale, model quality, or
online lift.

## Out of scope

- live model calls or external data ingestion;
- online LLM ranking or traffic allocation;
- GPU or large-model deployment;
- changing hard eligibility, safety, consent, or audit authority;
- a universal ranker for future discovery verticals.

## References

- [Immersive Discovery Architecture ADR](ADR-IMD-001-immersive-discovery.md)
- [Immersive Discovery Execution Plan](../IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md)
- [IMD-076 Execution Packet](../execution/immersive-discovery/IMD-076-llm-context-engineering.md)
