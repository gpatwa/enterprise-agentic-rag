# ADS-050: Structured Feedback and Correction Capture

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M5 (first packet; M5 is `in_progress`, its human gate `separation_of_duties_review` is untouched)
Depends on: ADS-042, ADS-047

## Decisions confirmed by the user

The proposal listed four decisions and the user replied "Go with your recommendations", which
confirmed: (1) the plan's default initial action scope, *read-only analytics plus reviewable change
proposals*; (2) evidence binding option (a): the v2 service seals evidence envelopes itself; (3)
backend and API only, no web control in this packet; (4) the free-text note is stored as written.

## Deliverable

- `packages/platform_contracts/feedback.py`: `FeedbackSubmission` (strict, what a caller may send:
  purpose, verdict, a fixed `reason_code` list, an optional correction, an optional note of at most
  2,000 characters), `ProposedCorrection` (names exactly one semantic ID, validated as an
  identifier so it cannot carry SQL or an expression), the frozen `FeedbackRecord`, and
  `FeedbackReceipt`. Everything about the run is bound by the server, never taken from the caller.
- Migration `0005_analytics_feedback` and `app/runtime/feedback_store.py`: an append-only,
  tenant-scoped table (database triggers reject UPDATE and DELETE on SQLite and PostgreSQL) with a
  composite foreign key to the run and idempotency per tenant, run, submitter, and key.
- `app/runtime/evidence_sealer.py`: the v2 service now seals a run's evidence envelope when it
  first reports the run terminal (idempotent; best effort, so a sealing failure never changes the
  response). `result_validation_node` gained an optional `report_sink` so the sealer has the
  validation report.
- `app/runtime/feedback_service.py`: requires an authorized purpose, a run visible to the caller's
  tenant and purpose, a terminal run, and sealed evidence; binds the record to the envelope's
  content, result, and intent fingerprints, contract version, and context snapshot; checks that a
  correction's semantic ID exists in the run's certified contract under the right kind (metric,
  dimension, or field).
- `POST /api/v2/analytics/runs/{run_id}/feedback` (`Idempotency-Key` required; 201 created, 200
  replay; 409 key reuse with a different body, `run_not_terminal`, `evidence_unavailable`; 422
  unknown or malformed correction). Unconfigured, it returns 503 `feedback_not_configured`.
- The reference stack wires sealing and feedback, and the smoke journey gained two steps (15 per
  dialect): feedback binds to sealed evidence, and replay is idempotent.

## Evidence

`services/analytics-api/tests/test_ads050_feedback.py` (11 tests, real graph, DuckDB, SQLite store):
feedback links run, evidence fingerprints, identity, reason, and snapshot; sealing happens once in
the service path; idempotent replay and key-reuse conflict; 401/403/404/400/422 handling including
a tenant-b caller and unknown extra fields; corrections accept only certified IDs of the right
kind and reject SQL-shaped values; non-terminal and unsealed runs are refused; refused runs accept
feedback without result evidence; stored records hold no SQL, rows, or policy values; the table
rejects UPDATE and DELETE; and feedback leaves the golden corpus, thresholds, semantic contracts,
and answers unchanged while the golden suite still meets its thresholds. `make
analytics-reference-smoke` passes. Full suite: 365 passed.

## Boundary

- **Recording only.** There is no triage, proposal, review, or promotion (ADS-051 to ADS-057) and no
  behavior ever reads feedback. The poisoning evaluation is ADS-059; this packet only shows there is
  no write path from feedback to goldens, thresholds, contracts, or the answer path.
- Notes are untrusted free text stored as written and may contain sensitive data; later packets
  that read them must treat them as data, not instructions.
- Any identity in the same tenant and purpose can submit feedback on a run; there is no per-user
  read restriction because nothing reads feedback yet. There is no rate limit.
- Sealing relies on process-local stores for the validation report (and answers, as before), so a
  restart can leave a succeeded run unsealed and feedback refused with `evidence_unavailable`.
- The v2 runtime is still not wired into the production app; feedback is inert like the rest.
- No web UI control (deferred by decision).
