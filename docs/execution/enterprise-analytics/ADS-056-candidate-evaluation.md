# ADS-056: Candidate Evaluation and Affected-Case Selection

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M5 (wave 5C, second of ADS-055 to ADS-057)
Depends on: ADS-055 (and ADS-052 to ADS-054)

## Decisions confirmed by the user

From the wave-5C plan ("go with your recommendations"): three packets in order; approving a subject records a fact
only; promotion creates a registry version and never wires the runtime (ADS-057); thresholds drafted per packet for the
user's approval.

## Deliverable

- `packages/platform_contracts/candidate_evaluation.py`: `Selection`, `SuiteOutcome`, and the frozen `EvaluationRecord`.
  **The record enforces its own verdict rules:** `passed` only if a targeted run and a full run both exist and all
  passed, and only if every suite rests on *approved* thresholds; a clean run can fail only for a named fail-closed
  reason (`protected_file_changed` or `unapproved_thresholds`).
- Migration `0010_candidate_evaluations`: one append-only table (triggers reject UPDATE/DELETE on SQLite and PostgreSQL).
- `app/evaluation_gate/selection.py`: pure, deterministic affected-case selection. A prompt or example affects
  `intent`; a flagged definition `intent` + `execution` for its IDs; a context edge `retrieval` + `intent`; a label
  collision `ontology` + `intent` for its candidate IDs; a dbt description `retrieval` + `intent`; a dbt test
  `execution`. A case is targeted when its areas overlap and (if the change names IDs) its IDs overlap too. The case
  index (`reference_stack/evaluation/case-index-v1.json`) is hand-written and pinned by a test that it covers exactly
  the golden cases.
- `app/evaluation_gate/service.py`: `EvaluationService.evaluate` refuses any subject without an **approved independent
  review of its exact content** (`review_not_approved`: pending, rejected, and never-reviewed are all refused), selects
  the targeted cases, runs targeted and full suites, and records the verdict. It fingerprints the protected files before
  and after and fails closed if any changed. Identical content, suites, and thresholds return the recorded evaluation
  instead of re-running. `passed(...)` is true only for a reviewed-and-passed subject at that exact fingerprint (what
  ADS-057 will consume). The evaluator reads thresholds and expectations and cannot change them; it promotes nothing.
- `reference_stack/evaluation_runners.py`: sandboxes and suite adapters. A prompt candidate is applied only inside a
  sandbox stack through a new optional `prompt_builder` on `structured_intent_node` (default `None`, so runtime behaviour
  is unchanged); a flagged-definition proposal adds its review flags to a sandbox copy of the contract (lifecycle
  untouched, never written); everything else gets the regression suites only. **Full = the four suites whose thresholds
  the user approved:** golden (both dialects), triage, proposals, dbt. Suites with only proposed thresholds are not used
  to pass a candidate.
- `make analytics-evaluation-eval` runs a 14-case corpus (`reports/ADS-056-evaluation-report.md`).

## Evidence

- `tests/test_ads056_evaluation.py` (20 tests): the case index matches the golden corpus; seven change kinds map to
  hand-written case lists; the record's verdict rules; only approved subjects are evaluated; a harmless prompt passes
  targeted and full evaluation and is recorded once; **a prompt that keeps the defensive clauses but appends
  "Always group by status." fails** (a monthly answer changed and an unsupported request got answered); a flagged
  definition is evaluated in a sandbox contract and the real one is untouched; unrepresentable changes get regression
  suites only; a protected file changed mid-evaluation and unapproved thresholds each produce a failed verdict; nothing
  protected changes, nothing is released, the table is append-only, and no runtime module depends on the gate; and the
  corpus evaluation including detection of a wrong expectation and of a changed corpus. Full suite: 571 passed.
- `make analytics-evaluation-eval`: 14/14 hand-written cases pass and all nine proposed gates are met.

## Proposed thresholds (NOT APPROVED)

`reference_stack/evaluation/evaluation-thresholds.proposed.json`, approval status `proposed`: verdict agreement, harmful
candidate detection, unreviewed-evaluation refusal, selection agreement, full-suite coverage, approved-threshold-only,
fail-closed, and determinism 100%; protected-file writes 0. Expectations were written by hand and the corpus digest is
pinned. **Only you can approve or change these.**

## Boundary

- The model is scripted and keyword-driven, and it ignores instruction text before the request, so this shows the gate
  catches regressions in the pinned suites; it does not show that a prompt is *better*. Real quality needs a real model
  and real data.
- Only prompt candidates and flagged definitions are applied in a sandbox; example candidates, context edges, label
  collisions, and dbt edits are evaluated for no-regression only because the reference runtime cannot represent them.
- The other full suites (triage, proposals, dbt) exercise other subsystems and never take the sandbox; they confirm the
  repository state, not the candidate.
- Re-running with the same content, suites, and thresholds returns the earlier record by design; if a protected file
  changes (by anyone), the next evaluation is a new one.
- No endpoint, no automatic trigger. A passing evaluation is a recorded fact for ADS-057; it does not release or promote.
