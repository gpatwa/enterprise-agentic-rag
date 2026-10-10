# IMD-067: Ranking Inspector and Evaluation Comparison View

## Objective

Add an operator-facing ranking inspector that compares retrieval/ranking modes
and stages, displays redacted evidence, and avoids private feature/model
internals.

## Dependencies and Reads

- IMD-039, IMD-054, IMD-059, and IMD-063 are merged.

## Owned Files

- Modify/create inspector-specific files under `apps/discovery-web/src/` only,
  plus focused tests under that app.

## Requirements

- Compare lexical/vector/hybrid/pre-rank/full-rank modes with version,
  fallback, stage timing bucket, source, reason, and metric summaries.
- Render redacted candidate traces; never show raw query/history/vectors/social
  identities/provider payloads.
- Keep controls accessible, bounded, responsive, and stable across states.

## Validation

```bash
npm --prefix apps/discovery-web run typecheck
npm --prefix apps/discovery-web test -- --run
npm --prefix apps/discovery-web run build
```

## Commit

```text
feat(discovery-web): add ranking inspector
```
