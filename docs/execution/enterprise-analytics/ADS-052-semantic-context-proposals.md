# ADS-052: Semantic and Context Change Proposal Generator

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M5 (wave 5B, first of ADS-052 to ADS-054)
Depends on: ADS-051

## Decisions confirmed by the user

The proposal listed six decisions and the user replied "go with your recommendations", which confirmed:
(1) ADS-052 emits structured change requests with a closed operation list, plus draft-contract patches only
for *flagging* (no definitional edits); (2) the shared proposal contract and store are built here and reused
by ADS-053 and ADS-054; (3) ADS-053 will use a fixture dbt project under the reference stack; (4) ADS-054
candidate examples hold references and fingerprints only; (5) thresholds are drafted per packet for the
user's approval; (6) 052, then 053, then 054, each its own PR merged one at a time.

## Deliverable

- `packages/platform_contracts/proposals.py`: the shared `ChangeProposal` (always `status: proposed`,
  `created_by: system:proposal-generator`), `PatchOperation`, `proposal_fingerprint`, and `apply_patch`
  (preview only, returns a copy). **The contract enforces the safety properties itself:** a patch may only
  `add`/`replace` `/lifecycle` (only to `draft`), `/contract/version`, or `/contract/metadata`; a patch
  must explicitly set the lifecycle to draft; targets are identifiers, never expressions. Nothing a
  generator builds can certify, or touch a definition, policy, or dataset.
- Migration `0007_change_proposals`: two append-only tables (triggers reject UPDATE/DELETE on SQLite and
  PostgreSQL): `analytics_change_proposals` (immutable content) and `analytics_proposal_support` (one link per
  supporting triage record, so equal requests deduplicate and only *add support*).
- `app/proposals/rules.py` (`proposal-rules-v1`): pure rules over structured triage facts. A proposal needs a
  triage decision resting on system evidence (`both` or `system_evidence`) and a concrete certified target.
  The operation list is closed:
  - **P-10** `flag_definition_for_review` (triage `T-91`, a definition the intent already used): draft patch
    that sets `review_flags` in the new draft's metadata and changes nothing else.
  - **P-20** `add_context_edge` (retrieval `T-90`/`T-80` with a correction): a structured request naming the
    dataset and `contains`; no patch, because the ontology is generated from sources, not a contract file.
  - **P-30** `review_label_collision` (ontology `T-30`): names the ambiguity code and the candidate IDs.
  Nothing else produces a proposal: undetermined, policy, execution, intent, prose, claim-only and
  conflicting triage all return a reason (`claim_only`, `category_not_applicable`, `no_target`,
  `unknown_dataset`). A rewritten definition is never proposed.
- `app/proposals/service.py`: `ProposalService.generate(triage_id)` reads the triage record, feedback, sealed
  evidence, run state, and certified contract, writes only to the proposal tables, and returns the proposal or
  the reason. `preview_diff` renders a unified diff of the draft against the certified contract. There is no
  endpoint and no automatic trigger; the registry directory is never written.
- Reference stack: `proposal_service()`; `make analytics-proposals-eval` runs the corpus.

## Evidence

- `tests/test_ads052_proposal_rules.py` (17 tests): each rule, deterministic; every "no proposal" reason; the
  contract rejects certified/deprecated lifecycles, definition and policy paths, and expression-shaped targets.
- `tests/test_ads052_proposals.py` (19 tests, real runs): a disputed definition becomes a valid draft flag with
  full provenance and a readable diff; a retrieval miss becomes a context-edge request; an exhausted clarification
  becomes a label-collision review; runs that do not warrant a proposal produce none; duplicates add support only
  and are idempotent; generation is deterministic across independent stacks; an injected note changes nothing;
  the registry contracts, goldens, thresholds, triage corpus, runtime prompt, and manifest are byte-identical
  before and after and only the proposal tables gain rows; patches only produce drafts on allowed paths; tables
  are append-only and tenant-scoped; no proposal endpoint; and the pinned corpus evaluation, including detection of
  a wrong expectation and of a changed corpus. Full suite: 451 passed.
- Real defect found and fixed while building this: a run that never resolved a contract (for example a rejected
  planning step) made `generate` raise instead of returning "no proposal"; the applicability check now precedes the
  contract lookup, with a regression test.
- `make analytics-proposals-eval`: 11/11 hand-written cases pass and all seven approved gates are met
  (`reports/ADS-052-proposals-report.md`).

## Approved thresholds

`reference_stack/proposals/proposal-thresholds.json` (renamed from `.proposed.json`). The implementing agent drafted them and the user then wrote "ADS-052 and ADS-053 approved" (2026-10-09), recorded in that file and in the manifest (`M5.m5_*_threshold_approval`); the approval covers only these ADS-052 proposal-corpus thresholds, not the M5 `separation_of_duties_review` gate or independent review of any packet. The gates: proposal agreement,
provenance completeness, draft validity, determinism, and dedupe agreement 100%; never-certified violations 0;
protected-file writes 0. Expectations were written by hand from the rule definitions and the corpus digest is
pinned. Changing a threshold or the corpus digest needs a new explicit approval with a reviewed rationale.

## Boundary

- Proposals are requests, not fixes. The only patch produced adds a review flag to a draft; whether a definition,
  edge, or label should change is for a reviewer (ADS-055).
- `add_context_edge` and `review_label_collision` have no registry representation, so they carry no patch; where
  the ontology is actually edited is not yet defined.
- The corpus has 11 cases on the fakes-only stack; it shows the rules behave as written and are safe, not that the
  proposals are good.
- The draft version name embeds a fingerprint prefix; nothing writes the draft anywhere, so it exists only as a
  value on the proposal.
- Process-local run state (context pack, clarification candidates) is read from the control store; no production
  path calls the generator.
