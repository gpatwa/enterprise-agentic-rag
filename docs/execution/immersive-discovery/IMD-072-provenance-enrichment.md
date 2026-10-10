# IMD-072: Provenance-Preserving Metadata Enrichment

Status: complete

## Scope

Add a local-only, provider-neutral enrichment workflow for generated catalog
tags and descriptions. Generated values are derived proposals, never
authoritative catalog facts. This packet does not add routes, persistence, live
model calls, or deployment configuration.

## Safety contract

- Drafts contain only permitted generated fields, provider/model/prompt
  versions, source-content hash, timestamp, tenant, and experience identity.
- Source catalog text is untrusted data. It is passed to a provider boundary
  as data and cannot supply action, policy, identity, or eligibility fields.
- Provider failures and model-off mode produce a deterministic empty draft.
- Approval and rejection are explicit immutable transitions. Approval records
  review evidence but does not mutate the authoritative `ExperienceRecord`.
- Tenant ownership and eligibility remain caller-owned and are not inferred by
  enrichment.

## Owned paths

- `services/discovery-api/app/enrichment/`
- `services/discovery-api/tests/test_provenance_enrichment.py`
- this packet and the canonical execution-plan status

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_provenance_enrichment.py -q
ruff check services/discovery-api/app/enrichment services/discovery-api/tests/test_provenance_enrichment.py
git diff --check
```

## Commit

`feat(discovery): add provenance-gated enrichment workflow`
