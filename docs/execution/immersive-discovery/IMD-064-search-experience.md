# IMD-064: Discovery Search and Filter Experience

## Objective

Build the web search workflow over the typed search endpoint: exact and natural
queries, allowlisted filters, bounded pagination, and loading/empty/error
states with keyboard-accessible controls.

## Dependencies and Reads

- IMD-063 and IMD-060 are merged. Read only `apps/discovery-web` and API
  client contracts.

## Owned Files

- Modify/create search-specific files under `apps/discovery-web/src/` only.
- Add focused component tests under the same app.

Do not edit API, support/analytics apps, root package files, deployment, or
unrelated web modules.

## Requirements

- Preserve typed request/response and impression-token lineage.
- Cover exact ID/name and natural query, locale/device/age filters, pagination,
  loading/empty/error states, keyboard/focus, and redacted reasons.
- Keep layout stable and responsive; no raw profile/private data in UI.

## Validation

```bash
npm --prefix apps/discovery-web run typecheck
npm --prefix apps/discovery-web test -- --run
npm --prefix apps/discovery-web run build
```

## Commit

```text
feat(discovery-web): build search experience
```
