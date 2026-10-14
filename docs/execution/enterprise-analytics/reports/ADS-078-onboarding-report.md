# ADS-078: Second-Tenant and Apache Ossie Portability Onboarding Drill

**Result: MEETS the proposed thresholds.** The thresholds are PROPOSED and NOT APPROVED. The drill's "certification" is a transformation of a temp copy of the registry: **it is not a certification**, and the repository registry is never written.

## Metrics

| Metric | Measured | Gate | Meets | Plan gate |
|---|---:|---:|:---:|---|
| `code_and_schema_changes` | 0 | <= 0 | yes | Onboards without product-code or contract-schema changes: 0 changed files |
| `draft_import_served` | 0 | <= 0 | yes | An imported (draft) model served or compiled before certification: 0 |
| `second_tenant_result_equivalence` | 1 | >= 1.0 | yes | The second tenant's answer equals the independent oracle: 100% |
| `cross_tenant_contract_use` | 0 | <= 0 | yes | A tenant using another tenant's contract: 0 |
| `round_trip_id_stability` | 1 | >= 1.0 | yes | Export then import keeps dataset ids: 100% |
| `hostile_expressions_imported` | 0 | <= 0 | yes | Unsupported or hostile Ossie expressions that become metrics: 0 |
| `first_tenant_unchanged` | 1 | >= 1.0 | yes | The first tenant's answers are unchanged after onboarding: 100% |
| `round_trip_omissions` | 2 | >= 0 | yes | Metrics and time dimensions an export omits (informational; a documented subset, not a gate) |

## Steps

| Step | OK | Detail |
|---|:---:|---|
| import is a draft | yes | round_trip=exact_subset |
| draft is refused by the registry and the compiler | yes |  |
| the second tenant's answer equals the oracle | yes | got [['2025-02-01', '12460'], ['2025-01-01', '4650'], ['2025-03-01', '1190']], wanted [['2025-02-01', '12460'], ['2025-01-01', '4650'], ['2025-03-01', '1190']] |
| each tenant can use only its own contract | yes | own=completed |
| export then import keeps dataset ids | yes | export omits (by the ADS-008 subset): ['dimension.subs.billed_at', 'mrr'] |
| unsupported and hostile expressions are reported lossy and dropped | yes | metrics=['mrr'] |
| the first tenant still gets the oracle answer | yes |  |

## What a person must still do (not automated, not done here)

- The data owner reviews the imported draft: ownership, descriptions, grain, and the metric definition.
- A human adds policies (allowed purposes, classification, required filters); an import carries none, so nothing is answerable without them.
- Semantic certification (lifecycle and metric) by the certifying owner, in the Git-backed registry; the drill's sandbox flip is not this.
- A context snapshot, ontology labels/aliases, and a physical data source and gateway for the tenant are provisioned.
- The scripted model of the reference stack knows only the first tenant's phrasings; a real model with the tenant's context is needed for natural-language questions.

## Not measured

- **natural_language_for_tenant_b**: the drill compiles and runs an intent; the reference stack's scripted model only understands the first tenant, so end-to-end natural-language onboarding is not shown
- **policy_authoring**: an imported model has no policies; authoring and reviewing them is manual and not evaluated
- **real_ossie_models**: one small hand-written model in the pinned 0.2.0.dev0 subset; real-world Ossie documents, other versions, and lossy constructs beyond metric expressions are not exercised
- **live_warehouse**: a local Parquet file stands in for the tenant's warehouse
- **identity_and_groups**: the second tenant's identity provider mapping is not onboarded
- **export_of_metrics**: Ossie export carries datasets and fields only (the ADS-008 subset): metrics and time-dimension flags are not exported, so a round trip is not lossless. Whether export should carry metrics is a decision for the user; it would not change the Compass contract schema.
