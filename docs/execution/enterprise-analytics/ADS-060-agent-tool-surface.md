# ADS-060: Versioned Agent Tool Surface

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M6 (wave 6A, first of ADS-060, ADS-062, ADS-063)
Depends on: ADS-045

## Decisions confirmed by the user

Wave 6A scope ("go with that scope"): agents cannot approve reviews; rows are excluded from artifacts by default
(ADS-062); the identity suite runs against the local test issuer only (ADS-063); packets in order 060, 062, 063.

**One interpretation to confirm.** The scope said only a human identity can approve, "including one acting through a
delegated token". This packet reads that conservatively: a token that names an acting party (`act_sub`, `azp_agent`, or
`delegated_by`) is treated as an *agent* call and is refused for the review tool, as are `agent:`/`system:`/`service:`/
`model:` identities. A person approves only with a direct token. If you meant that an agent may carry a person's approval,
that is a one-line change in `caller_kind` and should be a separate, explicit decision.

## Deliverable

- `packages/platform_contracts/agent_tools.py`: the versioned catalogue (`agent-tools-v1`). Five tools, each with strict
  argument models (`extra=forbid`, size bounds, ID patterns): `analytics.analyze` (write, idempotency key required),
  `analytics.status` (read), `analytics.clarify` (write), `analytics.review` (decision, **human-only**), and
  `analytics.evidence` (read). Results (`ToolResult`) carry stable codes and a data-free `EvidenceSummary`; never SQL,
  physical names, policy values, rows, or free-text reasons.
- `app/agent_tools/dispatcher.py` (`AgentToolSurface`): validates the call, refuses unknown tools and invalid arguments
  without echoing them, applies the human-only rule, then calls the *same* `GovernedAnalyzeService` as REST, so
  authorization, purpose scope, idempotency, requester binding, and review separation of duties are unchanged. Unexpected
  exceptions become `internal_error` with no text. The evidence tool authorizes through `status()`, requires a terminal
  run, and reads the sealed envelope; `EvidenceStore.seal_position` (additive) supplies the chain position.
- `app/agent_tools/catalogue.py`, `catalogue.lock.json`, and `docs/execution/enterprise-analytics/agent-tools-catalogue.md`:
  the catalogue document is generated from the contracts and the lock pins the schema digest, so any schema change fails a
  test until the lock is regenerated (and, by convention, the version bumped).
- **No transport.** Nothing mounts the surface (no endpoint, no MCP server); `app.main` and `api_v2` do not import it.
  The MCP adapter is ADS-061.

## Evidence

- `tests/test_ads060_agent_tools.py` (32 tests): every tool has a strict schema and metadata; the lock and the generated doc
  match the code and a schema change changes the digest; ten invalid-argument shapes are refused without echoing the value;
  unknown tools and malformed calls are refused; a tool call and a service call give the same run and result; idempotency
  matches REST (replay, key reuse 409); purpose, tenant, and run scope fail closed; clarification is requester-bound; a human
  reviewer decides while the requester cannot approve their own run and a stale fingerprint is refused; six agent or
  delegated identities are refused (`human_required`) for both approve and reject and the run does not move; agents keep every
  non-decision tool; the evidence summary matches the sealed envelope and the chain position and holds no SQL, rows, or policy
  values; evidence needs a terminal run and a configured store; a refused run has evidence without result fields; unexpected
  errors do not leak their text; and nothing mounts the surface.

## Boundary

- The surface is a library: no transport, authentication, or session handling. A caller (the ADS-061 MCP adapter, or a test)
  supplies a verified `AnalyticsIdentity`.
- `caller_kind` recognises automated identities by the ADS-055 prefixes and delegation by three claim names. **Update (ADS-063):**
  the OIDC verifier now carries a valid RFC 8693 actor claim through as `act_sub`, `caller_kind` and `DELEGATION_CLAIMS` live in
  `app/security/identity.py` (re-exported from `app.agent_tools`), and the REST review endpoint applies the same human-only rule.
- The service's own `decide_review` applies the ADS-038 rules (no self-approval, plan fingerprint, expiry); the ADS-055
  automated-identity rule applies to the *candidate-review* workflow, not to run approval, which is why the human-only rule is
  enforced in this layer.
- A run's evidence is readable by any caller with the same tenant and purpose, like its status; there is no requester-only read.
