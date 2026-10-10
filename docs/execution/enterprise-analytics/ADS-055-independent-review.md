# ADS-055: Independent Review and Certification Workflow

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M5 (wave 5C, first of ADS-055 to ADS-057)
Depends on: ADS-052 to ADS-054

## Decisions confirmed by the user

From the wave-5C proposal ("go with your recommendations"): a `reviewer` role claim in the token, with the author and
feedback submitter excluded; review expiry of 72 hours (configurable); approving only records a fact, with no
wiring and no promotion in this wave; three packets in order (055, 056, 057), each with thresholds drafted for the
user's approval.

## Deliverable

- `packages/platform_contracts/review.py`: `ReviewSubject` (a proposal, prompt candidate, or example candidate at one
  content fingerprint, with every contributor), `ReviewRecord`, `ReviewEvent`, `ReviewStatus`, and the decision
  request. The reviewer role is membership of the `analytics-reviewer` group in the verified token.
- Migration `0009_reviews`: two append-only tables (triggers reject UPDATE/DELETE on SQLite and PostgreSQL): reviews
  and their ordered audit events.
- `app/review/rules.py`: pure separation-of-duties rules in a fixed order, so refusals have stable codes:
  `automated_identity` (any `system:`, `model:`, `agent:`, or `service:` identity), `not_a_reviewer`,
  `is_contributor` (the generator, the candidate's creator, **and every feedback submitter behind the subject**),
  `is_requester`, `already_decided_by_reviewer`. State is derived from events and time: a rejection is terminal,
  approvals need the required number of *distinct* reviewers, and an unfinished review expires.
- `app/review/subjects.py`: resolves the subject as it is now, with its content fingerprint and contributors. A released
  prompt baseline is not reviewable; only candidates are.
- `app/review/service.py`: `request_review` (one live review per exact content), `decide`, `status`, `expire_due`,
  `is_approved`. A decision is accepted only if the reviewer passes the rules, names the review's exact content
  fingerprint, the subject's *current* fingerprint still matches (`subject_changed` otherwise), and the review has not
  expired; the first expired decision records one `expired` event by `system:review-expiry`. **An approval records a
  fact about that exact content; it applies, certifies, and promotes nothing.**
- No endpoint, no automatic trigger, and no runtime module depends on reviews. `make analytics-review-eval` runs a
  20-case corpus (`reports/ADS-055-review-report.md`).

## Evidence

- `tests/test_ads055_review.py` (31 tests): state derivation including distinct approvers and expiry; every rule;
  the full workflow on a real proposal with an audit trail; each forbidden reviewer refused with no decision recorded
  (generator, model, feedback submitter, requester, non-reviewer, a token without the purpose, a purpose that cannot see
  the review, another tenant); a *second* person's supporting feedback also bars them; wrong fingerprint and changed
  subject refused; expiry audited once, `expire_due` idempotent, a renewed review is new; rejection terminal; two
  independent approvals and one person counting once; repeat requests return the live review; prompt and example
  candidates reviewable only by independent people; unknown subjects refused; tables append-only; approving (with a
  note that tells the system to certify and promote) changes no proposal, contract, golden, threshold, runtime prompt, or
  manifest, and the OpenAPI document is unchanged. Full suite: 551 passed.
- `make analytics-review-eval`: 20/20 hand-written cases pass and all nine proposed gates are met.

## Proposed thresholds (NOT APPROVED)

`reference_stack/review/review-thresholds.proposed.json`, approval status `proposed`: outcome agreement, forbidden-decision
rejection, stale-decision rejection, expiry enforcement, audit completeness, and determinism 100%; approvals without
independent review, subject mutations, and protected-file writes 0. Expectations were written by hand and the corpus
digest is pinned. **Only you can approve or change these.**

## Boundary

- Reviewers are reference-stack tokens with a group claim. There is no real identity provider, group sync, or revocation,
  so "independent" means a different identity in the same token model, not a verified different person.
- Contributor tracking covers the generator, a candidate's creator, and feedback submitters; someone who influenced a
  proposal in a way the records do not capture (for example by editing a file out of band) is not detected.
- Approval is per exact content fingerprint and does not expire once granted; the promotion controller (ADS-057) must
  decide how recent an approval has to be.
- A review and its approvals are advice to a later promotion step. They are **not** the M5 `separation_of_duties_review`
  human gate, and they do not make any ADS packet `complete`.
