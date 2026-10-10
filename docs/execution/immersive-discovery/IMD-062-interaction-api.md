# IMD-062: Interaction, Feedback, and Explanation Endpoints

## Objective

Add typed API routes for interaction events, feedback, and explanation lookup.
Events require valid lineage and consent; explanations are redacted and
reference the served decision/audit record.

## Dependencies and Reads

- IMD-050 and IMD-058 are merged. Read route/search/home patterns, ingestion,
  audit records, shared contracts, and the FastAPI scaffold.

## Owned Files

- Create `services/discovery-api/app/routes/interactions.py`.
- Create `services/discovery-api/tests/test_interaction_endpoints.py`.

## Requirements

- Strict bounded request/response models for event submission, feedback,
  explanation ID/decision reference, typed reason codes, and receipts.
- Delegate to ingestion/audit contracts; reject invalid/replayed/mismatched
  lineage, denied consent, unknown decisions, and extra/private fields.
- Keep raw query/history/vectors/social/provider payloads out of response and
  ordinary logs; deterministic local behavior only.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_interaction_endpoints.py -q
ruff check services/discovery-api/app/routes/interactions.py services/discovery-api/tests/test_interaction_endpoints.py
git diff --check
```

## Commit

```text
feat(discovery): add interaction and explanation endpoints
```
