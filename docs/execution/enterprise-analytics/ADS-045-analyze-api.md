# ADS-045: `POST /api/v2/analytics/analyze` and Resume Endpoints

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M4
Depends on: ADS-038, ADS-043

## Deliverable

| Endpoint | Purpose |
|---|---|
| `POST /api/v2/analytics/analyze` | Start (or replay) a governed run. Requires `Idempotency-Key` (8-128 chars `[A-Za-z0-9._:-]`). |
| `GET /api/v2/analytics/runs/{run_id}?purpose=` | Current state/outcome, scoped by tenant and purpose. |
| `POST /api/v2/analytics/runs/{run_id}/clarify` | Pick a candidate for a pending ambiguity (original requester only). |
| `POST /api/v2/analytics/runs/{run_id}/review` | Approve or reject a pending review against the plan fingerprint. |

- **Auth:** OIDC bearer token via the existing `OIDCVerifier`; the `X-API-Key` check, if
  configured, also applies. The caller's `purpose` must be in the token's purposes (403).
  Missing/invalid token is 401.
- **Idempotency:** `run_id = sha256(tenant:user:purpose:key)[:32]`. The same key and request
  returns the existing run (a terminal run is never re-executed; an active run with no live
  lease is resumed, which is crash recovery); the same key with different text is 409
  `idempotency_key_reused`. A concurrent duplicate create is detected by the primary key.
- **Outcome contract:** responses are `AnalyzeRunResponse{run_id, state, outcome}` where
  `outcome` is the existing `AnalyticsV2Outcome` union: `answer` (now also `claims`,
  `explanation_status`, `result` table, data-free `visualization`), `clarify`, `review`,
  `refuse`, `failed`. `state` is `running` (HTTP 202), `waiting_clarification`,
  `waiting_review`, or `terminal`. Terminal mapping: succeeded -> answer; refused ->
  `policy_restricted`; review_required -> `stale_metadata`; failures -> `query_timeout`,
  `executor_unavailable`, `planner_unavailable`, or `internal_error`. Responses carry stable
  codes, never SQL, physical names, or policy values.
- **Resume safety:** clarification is bound to the requester (a hash of the user ID is embedded
  in the run's `request_id`) and uses the existing two-turn limit; review decisions go through
  `ControlStore.resolve_review` (no self-approval, stale fingerprint 409, expiry).
- **Inert by default:** the router is included in `app.main`, but `v2_runtime` holds no
  service or verifier, so every call returns 503 `governed_runtime_not_configured`.

## Evidence

`services/analytics-api/tests/test_ads045_analyze_api.py` (9 tests) uses real graph-v2
stages, DuckDB execution, a SQLite control store with migrations, and signed JWTs:
grounded answer end to end; replay without re-execution, key reuse conflict, per-user run
isolation; 401/403/400/422/503 failures; tenant/purpose-scoped status; review pause with
self-approval blocked, stale fingerprint, approve -> answer, repeat -> 409; reject -> refuse
with no result; clarification (wrong user 403, bad candidate 422, two-turn limit ends in
refusal with nothing executed); OpenAPI paths and strict request schemas; the default app
being inert.

## Boundary

- No production wiring: no real model client, snapshot source, gateway registry, or control
  database is connected, and no OIDC JWKS is loaded from configuration. A deployment packet
  must construct `GovernedAnalyzeService` and set `v2_runtime`.
- Status reads are tenant+purpose scoped, not requester scoped (reviewers must see the run).
- The answer's rows and explanation come from process-local stores; a restart loses them and
  returns `internal_error` ("answer unavailable") for already-succeeded runs. Durable result
  storage is not part of this packet.
- Resume runs with the *resuming* caller's identity bindings in the runner factory; policy was
  already evaluated for the requester before the pause.
- The "edit" review action and run cancellation endpoints are not exposed.
- The ambiguity fixture keeps the reference ambiguous after a choice, so the tests exercise the
  limit path rather than a successful post-clarification answer.
