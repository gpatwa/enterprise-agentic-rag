# IMD-074: Offline LLM Relevance Judge

Status: complete

## Scope

Add a local-only, provider-neutral relevance-judge workflow for discovery
quality evaluation. It creates reviewable proposals without adding a route,
online ranking dependency, live model call, network access, or persistence.

## Safety contract

- Inputs contain only query/candidate IDs, bounded redacted text snippets, and
  evidence references. Identity, tenant, eligibility, and raw context fields
  are excluded from the judge contract.
- Every proposal includes prompt, provider/model, input digest, query/candidate
  IDs, evidence references, label, confidence, and explicit provenance.
- Human labels are a separate authoritative artifact. A review can merge a
  human label by proposal ID, but the judge proposal is never rewritten.
- Model-off mode returns an empty review. The deterministic fake is the only
  local provider and does not require a model SDK, network, or ranking route.
- Invalid provider output is skipped and cannot change golden fixtures or
  production ranking behavior.

## Owned paths

- `services/discovery-api/app/intelligence/judge.py`
- `services/discovery-api/tests/test_offline_relevance_judge.py`
- this packet and the canonical execution-plan status

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" \
  pytest services/discovery-api/tests/test_offline_relevance_judge.py -q
ruff check services/discovery-api/app/intelligence/judge.py \
  services/discovery-api/tests/test_offline_relevance_judge.py
git diff --check
```

## Commit

`feat(discovery): add offline relevance judge`
