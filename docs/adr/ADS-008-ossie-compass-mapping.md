# ADS-008: Apache Ossie to Compass Mapping

Status: Proposed for independent review
Mapping version: `ads-008.v1`
Ossie baseline: `0.2.0.dev0` draft core specification
Compass semantic contract: `v1`

This table is normative for the ADS-008 boundary. `Supported` means the
meaning can be represented and cross-reference validated by the current
Compass contract. `Compass-extended` means the value is outside Ossie core but
may be preserved in a namespaced Compass extension. `Lossy` means the source
value can be retained for review but cannot produce a certified equivalent.
`Unsupported` means the current boundary rejects or defers the construct.

## Core model mapping

| Ossie construct | Compass target | Classification | Mapping and safety rule |
|---|---|---|---|
| `version` | `metadata.ossie_spec_version` plus report | Supported | Must equal the pinned schema version; it is not the Compass contract schema version. |
| `semantic_model[].name` | `SemanticContract.id` and `metadata.ossie_model_name` | Supported | Preserve the original name; generate a namespace-qualified stable ID when the import does not provide one. |
| `semantic_model[].description` | `metadata.ossie_description` | Compass-extended | Compass `v1` has no top-level description field; descriptive text is not policy or certification evidence. |
| `semantic_model[].datasets` | `SemanticContract.datasets` | Supported | Each dataset needs a stable ID, source asset reference, physical name, description, and owner before certification. |
| `semantic_model[].relationships` | `SemanticJoin` | Supported for many-to-one | `from` is the many side, `to` is the one side, and key arrays retain positional order. Other cardinalities are rejected unless a future mapping version defines them. |
| `semantic_model[].metrics` | `SemanticMetric` | Supported for simple single-dataset aggregates | `SUM`, `AVG`, `COUNT`, `COUNT DISTINCT`, `MIN`, and `MAX` map only when the referenced field and grain are unambiguous. |
| `semantic_model[].ai_context` | `metadata.ossie_ai_context` | Compass-extended | Preserve after size and content checks; treat as untrusted retrieval context, never as authorization, policy, or executable instruction. |
| `semantic_model[].custom_extensions` | `metadata.ossie_custom_extensions` | Compass-extended | Preserve opaque JSON with vendor name and source fingerprint. Never interpret an extension as a policy or compiler instruction without a separate contract. |

## Dataset and field mapping

| Ossie construct | Compass target | Classification | Mapping and safety rule |
|---|---|---|---|
| `dataset.name` | `SemanticDataset.id` | Supported | Names are source identifiers; collisions are rejected unless the import namespace makes them unique. |
| `dataset.source` | `SemanticDataset.source_asset_id` and `physical_name` | Supported with validation | Parse only an allowlisted physical reference. A query string is not a physical source and is rejected for certified import. |
| `dataset.description` | `SemanticDataset.description` | Supported | Required by Compass; missing text keeps the contract draft or produces a validation error. |
| `dataset.primary_key` | `SemanticEntity.grain.key_field_ids` | Supported | Create an entity for the dataset when key fields resolve; preserve key order. |
| `dataset.unique_keys` | `metadata.ossie_unique_keys` | Lossy | Preserve as an extension, but Compass `v1` does not use alternate unique keys for join or metric safety. |
| `dataset.fields` | `SemanticField` collection | Supported for simple fields | Each field must resolve to one dataset and a supported Compass data type. |
| `field.name` | `SemanticField.id` and `physical_name` | Supported | Preserve dataset qualification through the stable Compass field ID. |
| `field.expression` with one simple column reference | `SemanticField.physical_name` | Supported | Accept an unquoted, non-computed column reference only after identifier validation. |
| `field.expression` with computed or qualified SQL | `metadata.ossie_field_expression` | Lossy | Preserve the source expression for review; do not place it in the certified Compass contract or typed intent. |
| `field.expression.dialects` | `metadata.ossie_dialect_expressions` | Lossy | Dialect expressions are evidence of source intent, not executable SQL. A dialect-specific expression cannot be certified without a Compass expression contract. |
| `field.dimension.is_time=true` | `SemanticDimension.dimension_type=temporal` | Supported | The field must resolve to a supported date/timestamp type. |
| `field.dimension.is_time=false` | `SemanticDimension.dimension_type` inferred from type | Supported with review | Map to categorical, numeric, or identifier only when deterministic; otherwise keep draft. |
| `field.label` | `metadata.ossie_field_label` | Lossy | Preserve as display metadata; it does not define business meaning. |
| `field.description` | `metadata.ossie_field_description` | Lossy | Compass `v1` field has no description slot; retain for context but do not use as certification evidence. |
| `field.ai_context` | `metadata.ossie_field_ai_context` | Compass-extended | Sanitize and scope to the field; never treat instructions as executable behavior. |
| `field.custom_extensions` | `metadata.ossie_field_extensions` | Compass-extended | Preserve opaque vendor data under the field identity and source fingerprint. |

## Metric and relationship mapping

| Ossie construct | Compass target | Classification | Mapping and safety rule |
|---|---|---|---|
| `metric.name` | `SemanticMetric.id` | Supported | Must be unique across Compass semantic assets. |
| Simple aggregate expression over one dataset field | `aggregation`, `measure_field_id`, `dataset_id` | Supported | Parse only the allowlisted aggregate shape; no arbitrary SQL parser fallback is allowed. |
| `COUNT(*)` | `aggregation=count`, dataset grain | Supported with explicit grain | The source dataset and row grain must be known; otherwise the metric is lossy. |
| `COUNT(DISTINCT field)` | `aggregation=count_distinct`, `measure_field_id` | Supported | The field must be a valid identifier in the metric dataset. |
| `AVG`, `SUM`, `MIN`, `MAX` over one field | Matching `SemanticMetric.aggregation` | Supported | Preserve the Compass grain and field type. |
| Metric expression over multiple datasets | `metadata.ossie_metric_expression` | Lossy | Preserve the expression, but do not certify because Compass `v1` metrics have one dataset and do not encode arbitrary cross-dataset formulas. |
| Ratio or derived metric | `SemanticMetric` ratio only when decomposable | Lossy by default | Accept only when the source maps to two named Compass metrics with a validated ratio; arbitrary formulas remain draft/lossy. |
| Cumulative, window, period-over-period, or nested aggregate | None in Compass `v1` | Unsupported | Reject from certified import; preserve source only in the report or extension. |
| `relationship.from` / `relationship.to` | `from_dataset_id` / `to_dataset_id` | Supported | Require two distinct datasets. |
| `from_columns` / `to_columns` | `from_field_ids` / `to_field_ids` | Supported | Arrays must have equal length and preserve positional pairing. |
| Relationship cardinality | `SemanticJoin.cardinality=many_to_one` | Supported for Ossie core | The current Ossie core describes many-to-one relationships. Do not infer other cardinalities from names. |
| Relationship `ai_context` | `metadata.ossie_join_ai_context` | Compass-extended | Preserve as context only; it cannot approve a join. |

## Trust, lifecycle, and operational mapping

| Compass concern | Ossie representation | Classification | Rule |
|---|---|---|---|
| `tenant_id` | `COMMON`/`COMPASS` extension or import request context | Compass-extended | Required by Compass. If absent, the imported contract is draft-only and cannot enter a tenant context pack. |
| Stable Compass IDs | `COMPASS` extension with source-to-target ID map | Compass-extended | Required for reliable round-trip; generated IDs must include source namespace and source fingerprint. |
| Contract `version` and schema version | `COMPASS` extension plus report | Compass-extended | Keep distinct from Ossie `version`; no implicit version coercion. |
| Registry lifecycle: `draft`, `certified`, `deprecated` | `COMPASS` extension | Compass-extended | Imported models default to `draft`; Ossie has no authority to certify or deprecate a Compass contract. |
| Owners | `COMPASS` extension | Compass-extended | Owner identity must be resolved by Compass; a display name in Ossie is not approval. |
| Provenance: source, version, observed/effective time, fingerprint | `COMPASS` extension plus report | Compass-extended | Required before certification; missing or conflicting provenance blocks the certified path. |
| Classification and data policy | `COMPASS` extension | Compass-extended | Preserve references only. Actual authorization remains the source system and Compass policy gate. |
| Required filters and identity filters | No Ossie core equivalent | Unsupported | Do not encode authorization or tenant filters in `ai_context`, metric expressions, or opaque SQL. |
| Quality, freshness, lineage, and run evidence | No Ossie core equivalent | Unsupported in core | Keep in Compass context sources and evidence; optional extensions are informative only. |
| Verified queries / approved examples | Roadmap or extension only | Unsupported in `ads-008.v1` | Do not treat examples as executable or authoritative; a future mapping may define a reviewed representation. |
| Ontology concepts and logical mappings | Separate Ossie ontology work | Unsupported in `ads-008.v1` | Defer to ADS-010/011 after the core semantic mapping is stable. |
| Customer rows, credentials, tokens, private audit payloads | No Ossie representation | Unsupported | Never export or derive these from an Ossie model. |

## Compatibility outcomes

| Outcome | Meaning | Certified execution allowed |
|---|---|---|
| `exact_subset` | Supported core fields canonicalize and round-trip unchanged. | Yes, after normal Compass ownership, provenance, policy, and certification review. |
| `extension_preserved` | Compass-only data survives in a recognized extension. | Yes only for the supported semantic subset; extensions do not grant authority. |
| `lossy` | Source meaning is retained for review but cannot be reconstructed by Compass `v1`. | No. Keep as draft or request human remediation. |
| `rejected` | The input is invalid, unknown-versioned, ambiguous, or unsafe. | No. |

## Required report fields

Every future import/export report must include:

```text
operation: import | export
ossie_spec_version
ossie_schema_fingerprint
mapping_version
compass_contract_version
source_reference
source_fingerprint
tenant_id: present | absent
provenance: complete | incomplete | conflicting
supported_paths[]
extended_paths[]
lossy_paths[]
unsupported_paths[]
round_trip: exact_subset | extension_preserved | lossy | rejected
certification_eligible: true | false
```

The report is review evidence. It is not a substitute for semantic
certification or source-system authorization.
