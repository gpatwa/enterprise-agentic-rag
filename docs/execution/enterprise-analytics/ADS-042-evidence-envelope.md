# ADS-042: Immutable Evidence Envelope and Append-Only Persistence

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M4
Depends on: ADS-041

## Deliverable

- `packages/platform_contracts/evidence.py`: `EvidenceEnvelope`, a frozen,
  content-addressed (SHA-256) record of one terminal run: identity, graph version,
  context snapshot ID, terminal kind, intent fingerprint and `contract@version`,
  policy decision, cost estimate/observed units, approval, result and validation
  fingerprints, clarification, cancellation, errors, the full transition history,
  and the terminal outcome's evidence fingerprints. It holds fingerprints,
  identifiers, and stable codes only: no SQL, parameters, policy values,
  `policy_values_reference`, rows, or free-text reasons.
- **Required provenance is enforced by the model**, per terminal kind:
  `succeeded` needs intent, contract, an allowing policy decision, a cost estimate,
  an acceptable result validation (and an `approved` review if one occurred);
  `refused` a `policy_denied` error; `review_required` a `stale_context` error;
  `clarification_required` clarification evidence; `failed` an error; `cancelled`
  cancellation evidence. Transitions must be contiguous from 1 and end at the
  terminal transition.
- `app/runtime/evidence.py`: `build_evidence_envelope(state, transitions,
  validation=...)` seals a terminal `AgentRunState` plus its transitions (objects or
  durable replay rows). A validation report must be bound to evidence the run
  actually recorded (the `result_validate` node's fingerprint), otherwise
  `EvidenceBuildError`.
- `app/runtime/evidence_store.py` and migration `0004_evidence_envelopes`:
  `EvidenceStore.append` seals only an existing terminal run of the same
  tenant/purpose, once (idempotent for the identical envelope, `EvidenceConflictError`
  for a different one), in a per-tenant hash chain (`previous_hash`, `chain_hash`)
  with database triggers rejecting UPDATE/DELETE (SQLite and PostgreSQL).
  `verify_chain` recomputes every content address and link; `get` is tenant- and
  purpose-scoped. `record_terminal_evidence` replays the durable transitions and
  appends.

## Evidence

- `services/analytics-api/tests/test_ads042_evidence_envelope.py` (17 tests):
  every non-success terminal outcome of the ADS-039 graph (refused x2, review
  required x2, failed x4, cancelled) sealed with its required items and no
  sensitive values; the stub graph's "succeeded" runs correctly refuse to seal for
  want of result evidence; one real graph-v2 run (DuckDB execution through the
  gateway, ADS-041 validation, control totals) sealed as `succeeded`; mismatched
  report rejected; per-kind enforcement; chain linkage, idempotency, conflicts,
  tenant scoping, trigger rejection, and tamper detection.
- Bug found by the real run and fixed in ADS-040: gateway validation rejected the
  compiler's time-granularity SQL (`DATE_TRUNC` parses as `TIMESTAMP_TRUNC`).
  Regression test added to the ADS-040 suite.

## Boundary

- `clarification_required` is covered by contract tests only; no current graph path
  ends in that kind, and `review_approved`/`crash_resume` succeeded runs in the ADS-039
  stub graph cannot be sealed (by design).
- Append-only is enforced by triggers; someone with schema rights can still bypass
  them, which `verify_chain` detects. It does not defend against rewriting the
  whole chain. External anchoring/signing of chain heads is not included.
- PostgreSQL triggers are written but not exercised against a server; SQLite is.
- Nothing calls `record_terminal_evidence` automatically at run end yet (the ADS-045
  API/worker owns that), and ADS-043 explanation evidence is not part of this envelope.
