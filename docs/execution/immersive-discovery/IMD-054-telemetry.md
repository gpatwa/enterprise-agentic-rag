# IMD-054: Redacted Discovery Telemetry

## Objective

Add quality, latency, feature-age, and model telemetry with stage/cohort/version
dimensions and no query text, profile vectors, or private social data.

## Dependencies and Reads

- IMD-053 and IMD-059 are merged.

## Owned Files

- Create `services/discovery-api/app/telemetry/discovery.py`.
- Create `services/discovery-api/tests/test_discovery_telemetry.py`.

## Requirements

- Use strict bounded event models with stage, cohort, component/policy/model
  versions, latency buckets, outcome, and redacted IDs/digests.
- Reject raw query/history/vector/private social fields and non-finite values;
  support deterministic aggregation and no-op local sink.
- Keep metrics safe for synthetic demo evidence and explicit about missing data.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_discovery_telemetry.py -q
ruff check services/discovery-api/app/telemetry services/discovery-api/tests/test_discovery_telemetry.py
git diff --check
```

## Commit

```text
feat(discovery): add redacted discovery telemetry
```
