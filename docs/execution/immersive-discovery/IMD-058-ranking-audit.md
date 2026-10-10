# IMD-058: Append-Only Ranking Decision Audit Evidence

## Objective

Record append-only ranking decisions with eligibility/policy results, component
versions, reason codes, fallback state, and redacted evidence. Do not store raw
personal data or provider payloads.

## Dependencies and Reads

- IMD-052 through IMD-057 and IMD-059 are merged.

## Owned Files

- Create `services/discovery-api/app/audit/ranking.py`.
- Create `services/discovery-api/tests/test_ranking_audit.py`.

## Requirements

- Use immutable versioned records with tenant/request/decision digests, bounded
  candidate counts/reasons, eligibility/policy/fallback outcomes, timestamp,
  and canonical checksum.
- Enforce append-only/idempotent event IDs, no mutation/deletion through the
  writer, no raw query/history/vectors/social/provider payloads, and stable
  serialization for later evidence export.
- Support explicit local no-op/readback behavior and redacted failure reasons.

## Validation

```bash
PYTHONPATH="$PWD/services/discovery-api:$PWD" pytest services/discovery-api/tests/test_ranking_audit.py -q
ruff check services/discovery-api/app/audit services/discovery-api/tests/test_ranking_audit.py
git diff --check
```

## Commit

```text
feat(discovery): add ranking decision audit evidence
```
