# IMD-075: Intelligence Safety Policy and Kill Switch

Status: complete

## Scope

Add a local-only policy boundary for optional immersive-discovery intelligence.
It covers prompt-injection-shaped catalog, user, and query text; bounded input
budgets; redaction; reproducibility metadata; tenant-safe cache keys; and an
immediate kill switch. It does not call a model, network, OpenSearch, Azure,
or any production route.

## Safety contract

- Untrusted text is data, never an instruction channel. Injection-shaped input
  is quarantined and sensitive field values are redacted.
- Input and output budgets are explicit policy values. The current module uses
  a bounded token estimate and exposes the output budget to future providers.
- Policy, provider, prompt, cache, and routing versions are emitted as safe
  metadata without raw prompt content or secrets.
- Cache keys are SHA-256 digests containing the tenant only as key material;
  tenant IDs and content are never logged or returned in the key.
- `enabled=False` or `kill_switch=True` immediately selects the IMD-071
  deterministic adapter and blocks optional enrichment, judge, and refinement
  calls. Caller-owned identity, tenant, policy, and eligibility context is
  never stored or mutated.

## Owned paths

- `services/discovery-api/app/intelligence/safety.py`
- `services/discovery-api/tests/test_intelligence_safety.py`
- this packet and canonical execution-plan status

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_intelligence_safety.py -q
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests -q
ruff check services/discovery-api/app/intelligence/safety.py \
  services/discovery-api/tests/test_intelligence_safety.py
git diff --check
```

## Commit

`feat(discovery): add intelligence safety policy`
