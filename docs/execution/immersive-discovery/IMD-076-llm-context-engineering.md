# IMD-076: LLM Context Engineering and GenRec Experiment Boundary

Status: complete

## Scope

Freeze the provider-neutral contract and evaluation boundary for using an LLM
to compact catalog, user, and session context for immersive discovery. This
task is a design and contract milestone. It must not enable an online LLM
ranker, call a live model, download data, deploy cloud infrastructure, or add
an external dependency.

The outcome is a reviewed contract that lets a later task implement offline or
shadow context enrichment against the existing ranking pipeline, with a clear
path to evaluate a GenRec-style catalog-aware scoring experiment.

## Read first

- `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md`
- `docs/adr/ADR-IMD-001-immersive-discovery.md`
- `docs/execution/immersive-discovery/IMD-070-structured-intent-contract.md`
- `docs/execution/immersive-discovery/IMD-071-bounded-intent-adapter.md`
- `docs/execution/immersive-discovery/IMD-074-offline-relevance-judge.md`
- `docs/execution/immersive-discovery/IMD-075-intelligence-safety-policy.md`
- `services/discovery-api/app/ranking/contracts.py`
- `services/discovery-api/app/ranking/inference.py`

## Required decision record

Document a versioned `DiscoveryRankingContext` contract or equivalent that
defines:

- request, user, item, session, and candidate-set fields;
- authoritative versus derived fields and their source versions;
- deterministic compaction rules for repetitive history, cold start, and
  token-budget overflow;
- candidate IDs as a closed catalog set, with no LLM-created candidates;
- redaction, tenant isolation, consent, age, and safety boundaries;
- prompt/provider/model/cache metadata without raw sensitive history;
- timeout, token, cost, and cache budgets;
- offline and shadow-only modes plus deterministic fallback;
- promotion gates for relevance, policy violations, latency, cost, and
  model-on/model-off comparison.

The record must explicitly distinguish:

1. current deterministic serving;
2. near-term LLM-assisted context enrichment;
3. a future GenRec-style context encoder and catalog-aware scoring head.

## Owned paths

- `docs/adr/ADR-IMD-076-llm-context-engineering.md`
- `docs/execution/immersive-discovery/IMD-076-llm-context-engineering.md`
- `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md` only for the IMD-076 row or
  dispatch-wave status if required by the implementation

Do not change `services/`, `apps/`, shared contracts, lock files, deployment
files, or unrelated ADRs in this task. The implementation contract belongs to
a later packet after this decision is reviewed.

## Acceptance evidence

- The ADR contains the three-stage evolution boundary and a visual flow.
- Context fields, authority, compaction, candidate binding, budgets, fallback,
  and audit metadata are explicit and versioned.
- The future scoring head cannot bypass OpenSearch eligibility, policy
  re-ranking, or audit evidence.
- The packet names measurable local gates for relevance, safety, latency, cost,
  and model-on/model-off comparison.
- No live LLM, cloud resource, external dataset, or online ranker is required.

## Validation

```bash
rg -n "DiscoveryRankingContext|context|compaction|shadow|catalog-aware|GenRec|fallback|budget" \
  docs/adr/ADR-IMD-076-llm-context-engineering.md \
  docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md \
  docs/adr/ADR-IMD-001-immersive-discovery.md
git diff --check
```

## Commit

`docs(discovery): define LLM context engineering boundary`
