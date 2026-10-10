# ADS-057: Shadow, Canary, Promotion, and Automatic Rollback Controller

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M5 (wave 5C, last of ADS-055 to ADS-057)
Depends on: ADS-056 (and ADS-055)

## Decisions confirmed by the user

From the wave-5C plan ("go with your recommendations"): promotion only creates a new released registry version and
never wires the runtime; every step needs an approved independent review and a passing evaluation; thresholds are
drafted for the user's approval; three packets in order.

## Deliverable

- `packages/platform_contracts/rollout.py`: `RolloutPolicy` (shadow agreement, canary fractions and error limit, monitor
  error limit, maximum approval age, and an approval block), `RolloutRecord`, `RolloutEvent`, `ReleasePointer`,
  `RolloutStatus`. A policy is valid only with strictly increasing canary fractions in (0, 1], and an "approved" policy
  must record who approved it and when.
- Migration `0011_rollouts`: three append-only tables (rollouts, rollout events, active-version pointer; triggers reject
  UPDATE/DELETE on SQLite and PostgreSQL).
- `app/rollout/controller.py` (`RolloutController`):
  - **Gates to start** (fixed order, stable codes): the policy must be *approved* (`rollout_policy_not_approved`);
    purpose authorized; the starter must be human; the subject must be a prompt candidate; the review must be approved
    (ADS-055) and the approval no older than the policy allows; the evaluation must have passed (ADS-056); and the
    candidate's parent must still be the active version (`stale_parent`). The same candidate under the same policy is the
    same rollout.
  - **`advance`** does one stage: shadow, then each canary fraction. Every step re-checks the gates; a failed shadow
    agreement, a canary error rate over the limit, or a lost gate rolls the rollout back automatically.
  - **`promote`** needs every canary stage passed (`canary_incomplete` otherwise; no skipping) and creates the next
    released version through `PromptRegistry.release_promoted`, then appends the active pointer. It is idempotent.
  - **`monitor`** observes a promoted version and rolls back if it regresses.
  - **`rollback`** (automatic or manual, audited with its actor) only appends: if the rollout had been promoted, a pointer
    back to the baseline, and a `rolled_back` event. Released versions are write-once, so the released version stays in
    the registry; nothing, including runs and evidence, is deleted.
- Registry and contract: a released prompt may now be a *promotion* (`system:promotion`, with its parent, the candidate it
  came from, and the rollout that made it) as well as the baseline; `release_promoted` is the only way to create one and
  gives each a content-checked `vN`. Older entries keep their digests.
- `app/rollout/observers.py` and `reference_stack/rollout_observers.py`: the observer interface and simulated observers
  (a pinned request set served through sandbox stacks, with injectable faults).
- `reference_stack/rollout/rollout-policy.proposed.json`: the proposed policy, **status `proposed`**. The shipped
  controller therefore refuses to run until the user approves a policy.
- No endpoint, no automatic trigger. **Nothing in the runtime reads the registry, the released version, or the pointer.**
  `make analytics-rollout-eval` runs a 12-case corpus (`reports/ADS-057-rollout-report.md`).

## Evidence

- `tests/test_ads057_rollout.py` (14 tests): policy validity and the repository policy being `proposed`; a released prompt
  is the baseline or a recorded promotion and nothing else; start refused for automated starters, an unauthorized purpose,
  non-prompt subjects, the unapproved policy, and unreviewed, unevaluated, or harmful candidates; the happy path creates
  `v2` with full provenance, moves the pointer once, cannot skip stages, and is idempotent; a shadow disagreement, a canary
  regression, and a post-promotion regression each roll back automatically, with the pointer reverting to `v1` after a
  promotion and the released `v2` kept; **a rollback adds exactly one event and changes no run, evidence, feedback, review,
  or evaluation row**; a stale approval rolls back instead of promoting; manual rollback is audited and idempotent; a
  candidate derived from a superseded version cannot start; protected files are byte-identical, tables are append-only and
  tenant-scoped, and no runtime module depends on any of it. Plus the corpus evaluation with detection of a wrong
  expectation and a changed corpus. Full suite: 585 passed (about 4.5 minutes).
- `make analytics-rollout-eval`: 12/12 hand-written cases pass and all nine proposed gates are met, run under a policy copy
  that the test harness marks approved (the repository's policy stays proposed).

## Proposed thresholds (NOT APPROVED)

Two things await the user, both recorded as proposed:
1. **The rollout policy** (`reference_stack/rollout/rollout-policy.proposed.json`): shadow agreement 100%, canary fractions
   10% and 50% with 0% errors, monitor 0% errors, approvals valid for 168 hours. Until it is approved, no rollout can run.
2. **The corpus thresholds** (`reference_stack/rollout/rollout-thresholds.proposed.json`): outcome agreement, ungated-start
   refusal, bad-candidate rollback, pointer integrity, evidence preserved, and idempotency 100%; release mutations,
   runtime reads, and protected-file writes 0.

## Boundary

- There is no live traffic. Shadow, canary, and monitor use a pinned ten-request set through sandbox stacks with injected
  faults, so this proves the controller's logic, not production behaviour. Real error rates, sample sizes, and canary
  fractions must be decided against real traffic.
- Promotion makes a candidate prompt a *system* release, even if its feedback came from one tenant. The text is a template
  with no tenant data, but promoting a tenant-derived prompt globally is a policy decision the user should confirm.
- The active pointer is a record of what a consumer *would* use. Wiring the runtime to read it is a behaviour change that
  needs its own separately approved step; until then promotion changes nothing a user sees.
- Only prompt candidates are promotable. Proposals and example candidates have no runtime effect to roll out; their
  promotion (a person applying a change) is outside this packet.
- The controller trusts its injected review and evaluation services; it does not re-run the suites at each step, so the gates
  can only reflect what those records say (the approval age is the freshness bound).
