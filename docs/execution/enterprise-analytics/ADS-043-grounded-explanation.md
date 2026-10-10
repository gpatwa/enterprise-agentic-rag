# ADS-043: Grounded Explanation and Visualization-Spec Node

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M4
Depends on: ADS-041, ADS-042

## Deliverable

`app/execution/explanation.py`:

- **`FactSheet`** is the only thing an explainer sees. It holds the result
  fingerprint, `contract@version`, semantic IDs (`metric:<id>`, `dimension:<id>`,
  `contract:<id>@<version>`), and result cells addressed by stable IDs
  (`cell:r<row>c<col>`, first 50 rows).
- **`verify_claims`** accepts a claim only if it cites at least one known result cell, every
  citation exists, and every number in the prose appears in a *cited* cell (comma and
  trailing-zero normalized). Violations are stable codes (`claim_0:ungrounded_number`,
  `unknown_citation`, `uncited`, `no_result_cell`, `bad_text`), never values.
- **`explain_result`** runs the (model-assisted) `Explainer` once, then at most **one
  repair attempt** that receives only the violation codes. If grounding still fails, or
  the explainer raises, the status is `evidence_only`: no prose, result and chart spec
  still returned. The result fingerprint is recomputed after every attempt;
  a change raises `ExplanationIntegrityError`.
- **`visualization_spec`** is deterministic from the intent shape (`stat`, `line` for time
  grain, `bar` for one dimension, `table` otherwise), binds column indexes to semantic IDs,
  and carries no data or model output.

`app/runtime/explain_stage.py`: `explain_node` loads the stored intent, contract, plan and
result, re-checks cheap invariants (truncation, shape, grain; control totals were enforced by
`result_validate`, the only legal predecessor), explains, stores the `Explanation` in the
process-local `ExplanationStore`, and returns a `decision` evidence reference carrying the
explanation fingerprint. Ungrounded prose never fails the run; an invalid or foreign result
does (`explain_result_invalid`, `explain_inputs_unavailable`, `explain_result_mutated`).

## Evidence

`services/analytics-api/tests/test_ads043_grounded_explanation.py` (12 tests): fact IDs,
every violation code, cross-cell number misuse, repair-fixes-prose, failed repair to
evidence-only, explainer exceptions, result mutation detected, chart-spec shapes, the node on
a real DuckDB result (grounded, degraded, truncated, foreign reference), and a full graph-v2
run (DuckDB, validation, explain) ending `succeeded` with a grounded explanation bound to the
validated result fingerprint. `test_ads042_evidence_envelope.py`'s real-run helper gained an
optional `explain` argument for this.

## Boundary

- No real model is wired: tests use scripted explainers. A production explainer client with
  pinned prompt/model is not part of this packet.
- Number grounding catches fabricated figures; it does not prove the prose's *meaning*
  (e.g. "highest", "grew") is true. Comparative wording is not verified.
- The explanation lives in a process-local store; it is not added to the sealed
  `EvidenceEnvelope` (only its fingerprint is a recorded decision reference). Durable
  storage and API exposure belong to ADS-045.
- Prose may quote result cell values; treat the stored explanation as result-sensitive.
