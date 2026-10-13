# ADS-062: Portable Machine-Readable Analysis Artifact

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M6 (wave 6A, second of ADS-060, ADS-062, ADS-063)
Depends on: ADS-042, ADS-060

## Decisions confirmed by the user

Wave 6A scope ("go with that scope"): rows are excluded from artifacts by default and included only on an explicit opt-in;
nothing mounts a transport yet.

## Deliverable

- `packages/platform_contracts/analysis_artifact.py`: `AnalysisArtifact` (`analysis-artifact-v1`), a frozen, content-addressed
  record of one *finished* run: outcome (`answer`, `refuse`, `failed`), the answer and its claims with citations, the
  visualization spec, the result shape (columns, row count, and a SHA-256 of the rows), the semantic contract and metric and
  dimension IDs, the context snapshot, and a pointer to the sealed evidence (envelope ID and fingerprint, chain position and
  hash, result fingerprint, validation status). `artifact_id` is `artifact:` plus the first 32 hex of the content fingerprint.
  **The model enforces consistency itself:** the outcome must match the sealed evidence's terminal kind, an answer carries its
  answer, result, visualization, and result fingerprint, a refusal or failure carries a reason code and no answer material,
  included rows must match their hash and count, and the fingerprint must match the content.
- **What the ID covers and what it never does.** It covers everything the run decided. It excludes the rows themselves and
  `rows_included` (so opting into rows never changes the ID) and it excludes timestamps, user IDs, the query ID, SQL, physical
  names, and policy values (so the same run yields the same artifact on every surface).
- `app/analysis_artifacts/builder.py`: `build_artifact` (from the public run response plus the evidence summary, the same two things the
  REST API and the ADS-060 tool surface expose), `artifact_for_run` (authorizes through the service, reads the sealed evidence),
  `parse_artifact` (strict; re-checks the fingerprint and rows hash), `verify_artifact` (against the live sealed envelope, chain
  position, snapshot, contract, result fingerprint, and the tenant's evidence chain), and `canonical_view` / `render_text`, which
  present an artifact from the artifact alone.
- No endpoint, tool, or transport yet; `app.main` and `api_v2` do not import the module.

## Evidence

- `tests/test_ads062_artifact.py` (24 tests): an answer artifact holds the decided content and none of SQL, physical names, policy
  values, timestamps, or user identifiers; rows are opt-in, hash-bound, and do not change the ID; the REST path, the tool surface,
  and the service all produce the same artifact, ID, canonical view, and text; a stored artifact replays without the service and
  the ID is stable across repeated reads and differs between different runs; **thirteen different tamperings** of a stored artifact
  (answer, claim text, citations, row count, rows hash, chain position, terminal kind, contract, snapshot, tenant, fingerprint,
  an extra field, the visualization) are each rejected, and changed rows are caught by their hash; verification passes against the
  live evidence, reports missing evidence, and reports a rewritten chain; refusals produce reason-code artifacts with no answer
  material; unfinished, foreign-tenant, and inconsistent runs cannot become artifacts; and nothing mounts the module.

## Boundary

- An artifact proves *consistency with the sealed evidence* and *integrity of its own content*; it does not prove the answer is
  correct, and an artifact that includes rows is as sensitive as the rows. Anyone holding one can read its claims and result shape.
- There is no signature: integrity comes from the content hash plus the tenant's evidence chain, which only the holder of the
  chain (this service) can check. A detached signature for offline verification is not included.
- Only finished runs (answer, refusal, failure) become artifacts. Clarification and review pauses are states of a run, not analyses.
- Replay is *presentation* replay (the same view from the artifact alone). It does not re-execute the query.
- The web app still renders from the REST response; switching it (and the ADS-061 MCP adapter) to artifacts is later work.
