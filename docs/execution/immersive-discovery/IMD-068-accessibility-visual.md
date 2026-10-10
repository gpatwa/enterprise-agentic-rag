# IMD-068: Responsive Accessibility and Visual Regression Coverage

## Objective

Add local accessibility and visual-regression coverage for the discovery web
workflow. Desktop/mobile screenshots must have no overlap/overflow; keyboard,
focus, reduced-motion, and contrast checks must pass.

## Dependencies and Reads

- IMD-064 through IMD-067 are merged. Read only the discovery web app and its
  existing test/build configuration.

## Owned Files

- Add/modify tests and test configuration under `apps/discovery-web/` only.
- Add stable local snapshot fixtures under that app only.

## Requirements

- Test desktop and mobile layouts across search, home, details, persona,
  feedback, and inspector states for overflow/overlap and stable dimensions.
- Test keyboard traversal/focus visibility, semantic labels, reduced motion,
  contrast-sensitive states, loading/error/empty states, and responsive media.
- Keep tests deterministic and local; do not introduce external services or
  unrelated UI changes.

## Validation

```bash
npm --prefix apps/discovery-web run typecheck
npm --prefix apps/discovery-web test -- --run
npm --prefix apps/discovery-web run build
```

## Commit

```text
test(discovery-web): add accessibility and visual coverage
```
