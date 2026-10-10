# ADS-051: Root-Cause Taxonomy and Deterministic Triage Rules

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M5
Depends on: ADS-050

## Decisions confirmed by the user

The proposal listed five decisions and the user replied "go with your recommendations", which
confirmed: (1) triage runs on demand, not automatically when feedback arrives; (2) no public endpoint
(no reviewer role exists yet); (3) triage may read the sealed envelope and the run's stored state;
(4) the plan's seven categories plus `none` and `undetermined`, nothing else; (5) corpus thresholds are
drafted for the user's approval rather than treated as approved.

## Deliverable

- `packages/platform_contracts/triage.py`: the taxonomy (`retrieval`, `ontology`, `intent`,
  `semantic`, `policy`, `execution`, `prose`, `none`, `undetermined`) and the frozen `TriageRecord`
  (category, rule ID, rules version, basis kind, evidence basis codes, alternates, conflict flag,
  evidence/feedback/decision fingerprints).
- `app/triage/rules.py`: ordered, pure, versioned rules (`triage-rules-v1`, 19 rule IDs). The inputs
  are structured fields only; there is no note field, so free text cannot steer a classification.
  **System evidence outranks the reporter's claim**: the run's errors, validation, and policy
  decision decide first (policy > intent > ontology > retrieval > execution > prose). When the
  reporter blamed somewhere else the system's category wins and `conflict` is set. Only when the run
  succeeded and validated do the reporter's structured claim and correction decide, and a correction
  is compared with the run's context pack (items plus graph closure, minus omitted) and the IDs the
  intent used: not retrieved -> `retrieval`; already used -> `semantic`; retrieved but not used ->
  `undetermined` (intent or ontology). Anything the rules cannot place is `undetermined` and lists its
  candidate causes; an unrecognised failure code is `undetermined`, never guessed.
- `app/triage/service.py` and migration `0006_feedback_triage`: `TriageService.triage` reads the
  feedback, sealed envelope, and stored run state and appends a record to an append-only table
  (triggers reject UPDATE/DELETE on SQLite and PostgreSQL). It is idempotent per rules version; a new
  version appends a new record, and the same version producing a different decision raises a
  conflict instead of overwriting.
- No endpoint, no automatic trigger, and nothing reads triage results.
- Reference stack: the fake ontology now has `contains` edges so metrics and dimensions reach the
  context pack through graph closure (as in the real builder); new stack options for omitting
  context ids and a cost budget; `make analytics-triage-eval` runs the corpus.

## Evidence

- `tests/test_ads051_triage_rules.py` (31 tests): every rule, conflicts, priority, determinism, and no
  free-text input.
- `tests/test_ads051_triage.py` (19 tests): real reference-stack runs classified by the documented
  rules (answer, policy denial, planning failure, exhausted clarification, cost-budget failure, not
  retrieved, definition disputed); injected notes do not change the decision; idempotency, versioning
  and conflict; append-only triggers; tenant scoping; feedback, goldens, thresholds, and contracts
  unchanged; no triage endpoint in the OpenAPI document; and the pinned corpus evaluation, including a
  check that a wrong label and a changed corpus are detected. Full suite: 415 passed.
- `make analytics-triage-eval`: 18/18 hand-labelled cases pass; all seven proposed gates are met. The
  report is `reports/ADS-051-triage-report.md`.

## Proposed thresholds (NOT APPROVED)

`reference_stack/triage/triage-thresholds.proposed.json`, approval status `proposed`:
category agreement and rule agreement 100%, determinism 100%, undetermined results naming candidates
100%, note independence 100%, claim-only decisions on failed runs 0, record mutations 0. The labels
were written by hand from the rule definitions and the corpus digest is pinned. **Only you can approve
or change these;** the report says "proposed" until the file records an approval.

## Boundary

- The rules are a first cut. `semantic` is inferred only from "the reporter's correction names an ID the
  intent already used", which is an inference, not proof the definition is wrong; the record marks it
  `both` (claim plus evidence), not `system_evidence`.
- Intent versus ontology cannot be separated from what is stored (the model's raw output and the
  resolution step's candidates are not sealed), so those cases are `undetermined` by design.
- The explanation's grounding status is not in the sealed envelope, so a prose fault is recognised only
  from an explain-stage failure or the reporter's `unclear_explanation` claim.
- 18 cases on the fakes-only reference stack show the rules behave as written; they say nothing about
  triage quality on real feedback, which needs real feedback and independent labelling.
- Triage reads the process-local context pack in the stored run state; no production path calls it.
