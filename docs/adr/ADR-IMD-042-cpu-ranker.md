# ADR-IMD-042: CPU Learned Ranker Decision

Status: Accepted for bounded local implementation
Date: 2026-08-24

## Context

The immersive discovery pipeline needs a full-rank stage after candidate
fusion and the deterministic pre-ranker. It must score only the supplied,
already-eligible candidate batch and must preserve the provider-neutral
ranking contracts from IMD-040. The first implementation is a local demo and
must remain reproducible, inexpensive, explainable, and usable without a
network service or accelerator.

IMD-041 supplies point-in-time, exposure-aware training examples. Those
examples and the IMD-007 metrics are sufficient for a bounded offline spike,
but the current corpus is synthetic. Any comparison below is therefore an
engineering selection decision, not evidence of production relevance or lift.

## Decision

Select LightGBM as the single approved CPU learned-ranker option for IMD-043
and subsequent bounded training/inference work. IMD-043 must add the pinned
dependency only after a clean local installation and import smoke test. The
initial implementation is restricted to a small tabular model, single-process
CPU execution, fixed seeds, and deterministic settings.

The approved initial dependency target is:

```text
lightgbm==4.5.0
```

The model is an optional stage. The deterministic linear/pre-rank path remains
the required fallback and is the behavior used when the model is disabled,
missing, incompatible, stale, over budget, or otherwise fails validation.
LightGBM cannot add candidates, alter eligibility, bypass policy, or mutate
request and provenance fields. Neural serving and LLM ranking are deferred.

## Bounded Spike Criteria

The spike compares a deterministic linear baseline, LightGBM, XGBoost, and a
neural option using the same frozen examples, feature projection, time-aware
split, candidate cap, and IMD-007 evaluation report. The comparison must record
the configuration, dataset checksum, feature-version checksum, model checksum,
seed, and runtime environment.

| Criterion | Linear baseline | LightGBM | XGBoost | Neural option |
|---|---|---|---|---|
| CPU latency | Excellent | Expected good for small trees | Expected good for small trees | Uncertain and usually higher |
| Reproducibility | Excellent | Good with one thread and fixed settings | Good with one thread and fixed settings | More difficult across runtimes |
| Missing values | Explicit feature defaults | Native support | Native support | Requires explicit preprocessing |
| Small-data quality | Strong baseline, limited interactions | Good candidate for bounded tabular data | Good candidate, more tuning surface | Not justified by the local corpus |
| Explainability | Direct weights | Feature importance and bounded contributions | Feature importance and bounded contributions | Lower operational explainability |
| Install footprint | Minimal | Moderate native wheel | Moderate native wheel | Large runtime and model footprint |
| License | Permissive | MIT | Apache-2.0 | Framework/model dependent |
| Local demo cost | Lowest | Low when bounded | Low to moderate | Highest |

The spike must not select a model from a single aggregate metric. A model is
acceptable only when it has no material regression on the reviewed quality
metrics, stays within the local latency and candidate-count budgets, produces
repeatable output, and passes all contract and eligibility checks. If those
conditions cannot be demonstrated on the synthetic corpus, retain the linear
fallback and record the result as inconclusive rather than claiming a lift.

## LightGBM Guardrails

The initial model configuration is intentionally conservative:

- small bounded tree count, depth, and leaf count;
- one CPU thread for repeatable local output;
- fixed seed and deterministic training settings;
- no network access, distributed training, GPU, or online updates;
- only frozen numeric features from the approved feature contract;
- time-aware validation with no future-event or post-impression leakage;
- bounded model size, training time, inference time, and candidate count;
- model and feature versions recorded with every inference result.

Training and inference must fail closed for unknown feature versions, missing
required fields, non-finite values, incompatible model artifacts, or an
ineligible candidate. On any such failure, the caller uses the deterministic
fallback and records a redacted reason code.

## Alternatives Considered

### Deterministic linear baseline

Retained as the mandatory fallback and a comparison baseline. It has the best
operational simplicity and reproducibility, but it cannot represent useful
bounded feature interactions as naturally as a tree model.

### XGBoost

Not selected for the first dependency. It is a credible CPU tabular option
with a permissive license and missing-value support, but it has a broader
configuration surface and does not provide enough local benefit to justify a
second tree-runtime dependency. Reconsider it only through a reopened ADR and
side-by-side evidence.

### Neural ranker

Deferred. The synthetic corpus, local cost target, explainability requirement,
and CPU-only demo do not justify neural serving. A neural option may be
re-evaluated when there is a sufficiently large consented dataset, a measured
quality gap, an inference budget, and an operational serving design.

## Rollback and Reopen Conditions

Rollback is a configuration and artifact operation: disable the learned flag,
route inference to the deterministic fallback, and retain the failed model
artifact and redacted evidence for diagnosis. No candidate or policy data is
modified by rollback. Remove the dependency in a later controlled change if
the local install smoke test or runtime budget fails.

Reopen this ADR if LightGBM cannot be installed reproducibly, violates the
latency, memory, or artifact-size budget, produces non-repeatable scores, fails
the ranking-contract gates, regresses reviewed metrics, or introduces a
licensing/security concern. Reopen it before adding XGBoost, a neural runtime,
an LLM ranker, GPU serving, online learning, or a hosted model service.

## Evidence and Non-Goals

The required evidence is a local, repeatable spike report with checksums,
metrics, resource measurements, and fallback behavior. It must clearly label
all generated examples and must not imply Roblox production behavior or
production ranking lift. This ADR authorizes no cloud deployment, live user
data, external model call, or changes to support or analytics products.

## References

- [Immersive Discovery Architecture](ADR-IMD-001-immersive-discovery.md)
- [Immersive Discovery Execution Plan](../IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md)
- [IMD-040 Ranking Contracts](../execution/immersive-discovery/IMD-040-ranking-contracts.md)
- [IMD-041 Training Examples](../execution/immersive-discovery/IMD-041-training-examples.md)
