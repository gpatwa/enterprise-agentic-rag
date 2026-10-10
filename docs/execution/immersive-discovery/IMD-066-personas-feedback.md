# IMD-066: Personas, Cold Start, and Local Feedback Controls

## Objective

Add explicit fictional persona selection, cold-start mode, consent state, and
local feedback controls that update later requests while keeping synthetic/demo
labeling visible.

## Dependencies and Reads

- IMD-051, IMD-063 through IMD-065 are merged.

## Owned Files

- Modify/create persona/feedback-specific files under `apps/discovery-web/src/`
  only, plus focused tests under that app.

## Requirements

- Make persona and personalization mode explicit; do not infer or fabricate
  private identity.
- Submit typed feedback with lineage, show optimistic/pending/success/error
  states, and update later local requests deterministically.
- Expose synthetic/demo and consent state visibly; preserve accessibility and
  responsive stable layout.

## Validation

```bash
npm --prefix apps/discovery-web run typecheck
npm --prefix apps/discovery-web test -- --run
npm --prefix apps/discovery-web run build
```

## Commit

```text
feat(discovery-web): add personas and feedback controls
```
