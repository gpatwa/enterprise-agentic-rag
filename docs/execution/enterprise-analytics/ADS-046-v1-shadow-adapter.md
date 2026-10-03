# ADS-046: V1 Shadow Adapter and Privacy-Safe Comparison Recorder

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M4
Depends on: ADS-045 (and the ADS-006 routing contract)

## Deliverable

`app/runtime/shadow.py`, wired into `POST /api/v1/analytics/query` in `app/main.py`:

- **V1 unchanged:** `query_with_shadow` awaits the legacy call first and returns that exact
  response object. Shadow analysis runs afterwards in a worker thread with a timeout; any
  shadow error, timeout, or recorder failure is swallowed (recorded as `error`/`timeout`).
- **Routing gate:** only a `RouteDecision` in `shadow` mode (`execute_governed=False`,
  `record_shadow=True`) is accepted (`require_shadow_decision`); legacy routes do no shadow
  work, and a route that forbids legacy execution refuses before calling v1.
- **Governed path cannot execute (enforced three ways):** `shadow_nodes()` replaces `approve`,
  `execute`, `result_validate`, and `explain` with blockers failing `shadow_execution_blocked`
  regardless of what the node factory supplies; the analyzer's `ShadowControlStore` rejects
  `create_review`/`resolve_review`/`revise_review`, so shadow cannot open a human review; and
  the factory receives only that guarded store. The run stops with a compiled, policy-checked,
  cost-estimated plan, so `outcome=plan_ready` means "would have been answerable".
- **Trusted identity:** shadow uses the verified bearer identity plus an
  `X-Analytics-Purpose` header that must be in the token's purposes. The untrusted
  `tenant_id`/`user_id` in the v1 body are never used. Missing, invalid, or mismatched
  credentials fall back to plain v1.
- **Recorder:** `ShadowComparison` holds the request fingerprint, legacy facts (status,
  counts, SQL fingerprint of normalized SQL, result fingerprint), governed facts (outcome,
  stable error codes, `contract@version`, intent fingerprint, metric/dimension IDs, plan
  reference, estimated cost, policy effect), an `agreement` class, and a column-count match.
  `governed_executed` is always `false`. No question text, SQL, parameters, or rows are
  recorded. The sink is a callable; `InMemoryShadowRecorder` is provided.
- **Inert by default:** `app.main.shadow_runtime` has no analyzer or verifier and a `legacy`
  default route, so v1 behaves exactly as before until configured.

## Evidence

`services/analytics-api/tests/test_ads046_shadow.py` (9 tests; the 045 test rig now exposes
`nodes()` for reuse): identical object returned with a canary-free record and zero warehouse
executions on a real DuckDB-backed graph; blockers replace even real nodes; an expensive plan
creates no review row; clarification and legacy-failure classification; analyzer error,
timeout, and broken sink leave v1 untouched; routing modes and mismatched identity refused;
the real v1 endpoint returns byte-identical JSON with and without shadow, and unverifiable,
wrong-purpose, no-purpose, or legacy-routed callers cause no shadow work.

## Boundary

- The governed side is never executed, so **results are not compared**, only answerability and
  shape (column count). Result-level parity needs a later, separately authorized step.
- Shadow runs are persisted in the control store as ordinary (failed-by-design) runs with a
  `shadow-` run ID prefix; no durable comparison table or migration was added, only the sink.
- The shadow analyzer's node factory, model client, and snapshot source are not wired in
  production, and no routing config is loaded from settings.
- Shadow work runs in the request's lifetime (after the v1 answer is computed, before it is
  returned), bounded by `timeout_seconds`; a background queue would remove that latency.
- A timed-out analyzer thread cannot be cancelled and may finish after the response.
