# ADS-047: Evidence-First Analytics Web Workflow

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M4
Depends on: ADS-045

## Deliverable

A **Governed** view in `apps/analytics-web` (`src/governed/`), separate from the unchanged v1
Workspace view:

- **Answer:** narrative, per-claim evidence chips showing the cited cell values (labelled with
  semantic IDs), a chart built from the data-free visualization spec, the result table, and an
  evidence panel (run ID, contract version, metric/dimension IDs, result fingerprint). The
  browser **re-verifies every claim** (citations resolve; every number comes from a cited cell)
  and flags any it cannot verify. `evidence_only` answers say no narrative was verified.
- **Clarify:** each certified candidate is a button that calls the clarify endpoint.
- **Review:** shows review ID, reason, expiry, and plan fingerprint; Approve/Reject are enabled
  only when the fingerprint is present. A reviewer signs in with their own token and opens the
  run by ID; the UI surfaces "someone other than the requester must decide".
- **Refuse / Failed:** plain explanation plus stable code; "Try again" only when retryable.
- **Running:** a polite live region; the page polls the run (bounded) until it settles.
- **Trace:** an ordered, client-side list of each step (submit, poll, clarify, review, replay).
- **Replay:** a read-only re-fetch of the same run; verified only if the run ID and result
  fingerprint are identical.
- Stable API error codes map to plain messages. The access token lives in component state only
  (never storage, URL, or build-time env).

Backend change: `AnalyticsReviewOutcome.plan_fingerprint` (additive, optional) is now returned
by the v2 API so a reviewer can bind a decision to the exact plan; asserted in the ADS-045 test.

## Evidence

- `npm test` in `apps/analytics-web`: **18 passed** (`workflow.test.ts`, `views.test.tsx`;
  Node test runner, esbuild bundling, React server rendering): citation resolution and
  re-verification (including forged numbers), chart specs, state mapping, polling bounds,
  replay verdicts, request shape (bearer, idempotency key, purpose, strict bodies), error
  mapping, and rendering of every outcome state.
- `tsc -b --noEmit` and `vite build` succeed.
- Manual run in the in-app browser against the real v2 router (DuckDB, SQLite control store,
  signed local test JWTs, a scratch server on a free port): review pause -> self-approval
  refused with the plain message -> reviewer approval -> grounded answer with chart, verified
  claims, evidence, and trace -> Replay verified. Console showed only the expected 403 and
  v1 `/health` 404s.

## Boundary

- The v1 header and nav items (History, Data sources) are unchanged placeholders.
- No browser E2E suite or visual regression tests; the live check above was manual.
- Token entry is a developer stand-in: there is no OIDC login flow, refresh, or logout.
- Trace and history are per page load only (not persisted); run IDs must be copied to reopen.
- The "edit" review action, cancellation, and feedback capture (ADS-050) are not in the UI.
- The Governed view needs a deployed runtime; nothing wires one in production yet (see ADS-045).
