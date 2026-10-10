# ADS-053: dbt Docs and Test Change Proposal Generator

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M5 (wave 5B, second of ADS-052 to ADS-054)
Depends on: ADS-051 (and the shared proposal contract and store from ADS-052)

## Decisions confirmed by the user

From the wave-5B proposal ("go with your recommendations"): ADS-053 uses a fixture dbt project under the
reference stack, an approved-files allowlist, and a validation command that is never run; thresholds are drafted
for the user's approval; one PR per packet.

## Deliverable

- **Fixture dbt project** (`reference_stack/dbt_fixture/`): a model with a schema file in canonical YAML, plus files
  that must stay out of scope (`dbt_project.yml`, SQL models, a macro, a singular test). It has no adapter,
  profile, or warehouse, so it cannot run.
- **Contract** (`packages/platform_contracts/proposals.py`, extending ADS-052): a new `DbtEdit` and the dbt
  operations. **The contract enforces the constraints itself:** a dbt edit may only target a `schema.yml` under
  `models/` (no `..`, no other file type), may only add one single-line description or one `unique`/`not_null`
  test, and a dbt proposal must carry validation commands that match exactly `dbt parse` or `dbt test --select
  <model>` and no registry patch. Only a dbt proposal may carry a dbt edit.
- `app/proposals/dbt_project.py`: a read-only view limited to approved patterns (default `models/**/schema.yml`),
  ignoring symlinks that escape the root, with a pure `render_edit` for diffs and tests. It never writes.
- `app/proposals/dbt_rules.py` (`dbt-proposal-rules-v1`): pure rules. **D-10** a `fanout_suspected` or
  `duplicate_group_keys` validation issue adds a `unique` test on the metric's single grain-key column; **D-15**
  `invalid_metric_value` adds `not_null` on the measure column; **D-20** a disputed definition (T-91) and **D-30**
  a retrieval miss (T-90/T-80) add a *missing* column description templated from the certified contract. A
  human-written description is never overwritten, and an existing test is never duplicated. Claim-only,
  undetermined, policy, prose, and composite-key cases yield a reason instead.
- `app/proposals/dbt_service.py`: `DbtProposalService.generate_dbt` reuses the ADS-052 stores and checks. It
  writes only to the proposal tables, does not import a process-spawning module, and never runs dbt. Equal
  requests share a proposal ID and add support; the fingerprint covers the request, not who raised it.
- `make analytics-dbt-eval` runs a 9-case corpus and writes `reports/ADS-053-dbt-proposals-report.md`.

## Evidence

- `tests/test_ads053_dbt_rules.py` (31 tests): every rule and every no-proposal reason; the contract rejects
  twelve disallowed paths, other tests, multi-line descriptions, unsafe commands, and a missing command list;
  the reader ignores unapproved files and symlink escapes; `render_edit` changes only the target column.
- `tests/test_ads053_dbt_proposals.py` (16 tests, real runs): a disputed definition and a retrieval miss become
  column descriptions with a one-line diff and the two validation commands; an applied edit on a temporary copy
  leaves valid YAML while the fixture stays byte-identical; narrowing the approved files yields "not found in
  approved files"; a `unique` test proposal is built from validation evidence through the real fact builder;
  duplicates, determinism, and an injected note ("run dbt build", "edit dbt_project.yml") change nothing;
  **process spawning is patched to raise and is never reached**; protected files and the fixture are unchanged
  and only proposal tables gain rows; semantic and dbt proposals from one triage record coexist; and the corpus
  evaluation, including detection of a wrong expectation, a changed corpus, and a spawn attempt.
  Full suite: 498 passed.
- `make analytics-dbt-eval`: 9/9 hand-written cases pass and all nine approved gates are met.

## Approved thresholds

`reference_stack/dbt_proposals/dbt-thresholds.json` (renamed from `.proposed.json`). The implementing agent drafted them and the user then wrote "ADS-052 and ADS-053 approved" (2026-10-09), recorded in that file and in the manifest (`M5.m5_*_threshold_approval`); the approval covers only these ADS-053 dbt-corpus thresholds, not the M5 `separation_of_duties_review` gate or independent review of any packet. The gates: proposal agreement,
provenance completeness, validation-command coverage, edit validity, determinism, and dedupe agreement 100%;
file-constraint violations, commands executed, and source-file writes 0. Expectations were written by hand from
the rule definitions and the corpus digest is pinned. Changing a threshold or the corpus digest needs a new explicit approval with a reviewed rationale.

## Boundary

- dbt is never run, so a proposed edit is not validated by dbt; the commands are text for a reviewer (ADS-055).
- The diff is against the PyYAML-canonical form of the file: comments and flow style in a real schema file would
  not survive a round trip, so the structured `DbtEdit` is the source of truth and the diff is a preview.
- D-10 and D-15 cannot be reached through the single-dataset reference API (no fan-out), so they are covered by
  unit tests and a real-fact-builder test with a sealed-envelope-shaped input, not by the corpus.
- Only single-column keys are supported for `unique`; composite keys return a reason. The `tests` versus
  `data_tests` key follows the column's existing key, defaulting to `data_tests`.
- The description templates state facts from the certified contract; whether the wording suits a project is a
  reviewer's call. There is no real dbt project, endpoint, or automatic trigger.
