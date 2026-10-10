# IMD-065: Personalized Home Feed and Item Details

## Objective

Build the home feed and item-details workflow with generated content, source /
reason evidence, safety/age metadata, and visible source diversity.

## Dependencies and Reads

- IMD-063 and IMD-061 are merged.

## Owned Files

- Modify/create home/details-specific files under `apps/discovery-web/src/`
  only, plus focused tests under that app.

## Requirements

- Use typed home/detail data and impression lineage; show consent/no-history
  fallback state without exposing private features.
- Render generated fictional content, source/reason labels, safety/age
  metadata, creator diversity, loading/error/empty states, and stable responsive
  cards/details without nested decorative panels.

## Validation

```bash
npm --prefix apps/discovery-web run typecheck
npm --prefix apps/discovery-web test -- --run
npm --prefix apps/discovery-web run build
```

## Commit

```text
feat(discovery-web): build home and details experience
```
