# Reviewer role and the review assistant

Decision (2026-10-21, the user asked whether an agent should hold `Analytics.Reviewer`): **no AI agent holds the reviewer role.**
The reviewer is the human check on expensive or unusual queries; an agent that approves them makes the check the model agreeing with
itself. The service already refuses review decisions from automated, delegated, and `agent:`/`service:` callers (`human_required`) and
from the requester.

## What an agent may do instead

A **review assistant** with its own application identity reads paused reviews and writes a short note for the human reviewer. It can
never ask a question or decide.

| Piece | Where |
|---|---|
| `GET /api/v2/analytics/reviews/pending` | pending, unexpired reviews for the caller's tenant (reviewer or assistant group) |
| `GET /api/v2/analytics/runs/{id}/review-brief` | the plan, SQL, parameters, estimated cost, mechanical checks, and an advisory with `decision_authority: none` (no rows: a paused run has not executed) |
| `python -m app.decision_support.agent` | lists pending reviews and prints a note for each; deterministic, no model tokens |
| Entra app role `Analytics.ReviewAssistant` | gives only the read-only `analytics-review-assistant` group |

## Guard rails (all tested)

- The Entra verifier recognises **app-only tokens** (`idtyp: app`, or no person claim such as `scp` or `preferred_username`). Such a
  token gets **no purposes** and keeps **only** the assistant group, whatever roles were assigned (even `Analytics.Reviewer`), and is
  marked as an automated caller. So an application can read briefs, but cannot ask a question or decide a review.
- The decision endpoint needs the reviewer group **and** a human caller; the requester and automated callers are refused.
- People's tokens must carry the delegated scope `access_as_user` (the Terraform app registration publishes it) or a user name.
- The assistant's output is a note on stdout; it sends nothing anywhere and changes no review state.

Never assign `Analytics.Reviewer` or `Analytics.Analyst` to an application. Keep at least two named human reviewers, since a requester
cannot approve their own run.
