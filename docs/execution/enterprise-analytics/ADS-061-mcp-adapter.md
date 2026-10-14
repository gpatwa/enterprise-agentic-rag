# ADS-061: MCP Adapter over the Same Application Service

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M6 (wave 6B)
Depends on: ADS-060 (and ADS-062, ADS-063 for the equivalence and identity tests)

## Decisions made under the user's delegation ("make the decision")

Recorded so any of them can be overturned:
1. **No MCP SDK dependency.** The adapter implements the small JSON-RPC 2.0 subset it advertises (`initialize`, `ping`,
   `tools/list`, `tools/call`, notifications), protocol version `2024-11-05`, tools capability only (no resources, prompts, or
   sampling). A dependency would not change the boundary, only enlarge it.
2. **Per-message authentication.** The transport supplies a bearer token; every message is resolved through `IdentityResolver`, so a
   disabled person or a removed group is refused on the very next message. The token is never a message field.
3. **Tool names** are the catalogue names with `.` replaced by `_` (`analytics_analyze`), because MCP tool names are letters,
   digits, underscore, and hyphen.
4. **Failures are tool errors, not protocol errors**: a refused call returns `isError: true` with the same stable code the REST
   API and the tool surface use. Protocol errors are reserved for malformed JSON-RPC, an unknown tool name, and authentication
   (`-32001`).
5. **Audit lives in the tool surface**, not the adapter, so every transport (MCP, direct, a later HTTP one) is audited the same way.

## Deliverable

- `app/mcp/adapter.py` (`McpAdapter`, `serve_lines`): a transport-neutral adapter and the line-delimited stdio framing. It imports
  only the tool surface and the identity layer (a test parses its imports): no store, gateway, compiler, or service.
- `app/agent_tools/audit.py` (`ToolAudit`): an append-only, hash-chained audit (the existing `AuditChain`) of every tool call on
  every transport. An event holds the tool, transport, outcome, error code, a SHA-256 of the arguments, and a hash of the run ID:
  never argument values, tokens, SQL, rows, or the question text. Unauthenticated attempts are recorded with no caller details.
  `AgentToolSurface.call` gained `transport` and an optional `audit`; both default to the previous behaviour.
- No endpoint is mounted and `app.main` / `api_v2` do not import the module.

## Evidence

- `tests/test_ads061_mcp.py` (12 tests): the protocol subset (initialize, ping, notifications get no reply, parse error, batches
  and malformed envelopes, oversize, unknown method); `tools/list` mirrors the catalogue schemas and carries read-only and
  non-destructive hints; every message needs a valid token (none, empty, garbage, expired, unknown person) and a directory change
  applies to the next message; an MCP call gives the same run, rows, and evidence as REST, and the same artifact; tool failures are
  tool errors with the REST codes; **identity can never come from arguments** (`tenant_id`, `user_id`, `identity`, `groups` are
  rejected as invalid arguments); the adapter's import list is enforced; review stays human-only and requester-separated over MCP
  (own approval, a delegated token, and a stale run do not move it, a human reviewer can); another tenant cannot reach a run;
  every call is audited (refusals and invalid arguments too) with no argument values, tokens, SQL, or data; the chain detects a
  rewritten event; and line framing returns one line per request and never echoes the token.

## Boundary

- Only stdio-style line framing is provided. HTTP/SSE or WebSocket MCP transports, session management, and per-connection
  rate limits are not built; a launcher must supply the token (for stdio, from its environment).
- The audit chain is in memory, like the existing `AuditChain`. Persisting it (and anchoring its head) is an operations concern for
  a later packet (ADS-065, ADS-068).
- MCP clients hold a token for the session; a leaked token is usable until it expires or the directory disables the person.
- Prompt-injection through a tool's *content* (a claim or answer text read by a model client) is not an adapter property; ADS-067
  covers it.
