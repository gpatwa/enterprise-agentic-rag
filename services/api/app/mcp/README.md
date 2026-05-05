# MCP integration

Tier-1 SaaS connectors for Compass via Anthropic's [Model Context Protocol](https://modelcontextprotocol.io).

> **Phase status**: Phase 1 (infrastructure) and Phase 2 (real-subprocess proof) shipped. Phases 3–5 (more servers, OAuth, HTTP routes, UI) are pending.

## What this gives you

A new family of agent tools, qualified as `{server}.{tool}`:

- `slack.search_messages`, `slack.list_channels`, ...
- `github.list_issues`, `github.get_pull_request`, ...
- `notion.search`, `notion.read_page`, ...
- `gdrive.search`, `gdrive.read_file`, ... (Phase 4 — needs OAuth)

The agent's planner sees these per-tenant — only servers a tenant has enabled show up. Static tools (`calculator`, `vector_search`, `web_search`, etc.) are still in the registry and unaffected.

## How it works

```
Agent planner picks `slack.search_messages`
    ↓
agents/nodes/tool.py routes namespaced names to mcp_manager.call_tool
    ↓
manager looks up MCPConnection row, decrypts creds (Fernet)
    ↓
process_pool spawns `npx -y @modelcontextprotocol/server-slack` if needed,
caches the live ClientSession per (tenant, server) for reuse,
reaps idle subprocesses after MCP_IDLE_REAP_SECONDS
    ↓
ClientSession.call_tool over JSON-RPC stdio → result returned
    ↓
Audit emitted as event_type="mcp.tool_call"
```

## Enabling MCP in a deployment

1. **Install Node.js on the host.** The MCP servers run as child processes via `npx`. The image needs Node 20+.
2. **Bump fastapi/starlette** to a release that allows `mcp>=1.18` (verified compatible matrix: `fastapi==0.119.x`, `starlette==0.48.x`, `mcp==1.18.x`). The default `requirements.txt` keeps the conservative `fastapi==0.109.0` pin so existing deploys are not affected.
3. **Add `mcp>=1.18,<2.0`** to your build's requirements.
4. **Generate and store the master encryption key.** This is a 32-byte URL-safe base64 Fernet key:
   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Store it under the secret name `MCP_ENCRYPTION_KEY` in your secrets vault (Azure KV / AWS Secrets Manager). For local dev you can just export `MCP_ENCRYPTION_KEY=...`.
5. **Set `MCP_ENABLED=true`** in your environment.
6. **Apply the Alembic migration.** The `mcp_connections` table is created by either `Base.metadata.create_all()` on first boot OR an explicit `alembic upgrade head` (revision `0002_mcp_connections`).
7. **Enable a connection per tenant** via the CLI helper (Phase 5 will add HTTP admin routes):
   ```bash
   SLACK_BOT_TOKEN=xoxb-... SLACK_TEAM_ID=T0... \
     python -m services.api.scripts.mcp_enable \
       --tenant default --server slack --from-env
   ```
   Once enabled, the next agent run will see the new tools in the planner.

## Env-var reference

| Variable | Default | Purpose |
|---|---|---|
| `MCP_ENABLED` | `false` | Master switch — enables the manager + lifespan init |
| `MCP_ENCRYPTION_KEY` | _(none)_ | 32-byte URL-safe-b64 Fernet key for credential encryption |
| `MCP_IDLE_REAP_SECONDS` | `600` | After this much idle, a subprocess is torn down |
| `MCP_MAX_PROCESSES` | `200` | Pod-wide cap on simultaneously-live subprocesses |
| `MCP_TOOL_TIMEOUT_SECONDS` | `30` | Per-call timeout — bounds hung tools |

## Running the integration tests

The unit tests in `tests/test_mcp.py` (24 tests) need no external dependencies and run as part of the standard suite. They use a test seam (`_stdio_client_factory`, `_client_session_factory`) so the entire concurrency surface is exercised without a real subprocess.

The integration tests in `tests/test_mcp_integration.py` spin up a real `@modelcontextprotocol/server-everything` subprocess and exercise the full stack. They are **opt-in** — every test skips unless all three conditions are met:

- `MCP_INTEGRATION_TESTS=1` exported
- `node` and `npx` on PATH
- `mcp` package importable

To run them:

```bash
cd services/api
MCP_INTEGRATION_TESTS=1 python3 -m pytest tests/test_mcp_integration.py -v
```

First run downloads `@modelcontextprotocol/server-everything` via npx (~10–20s on a cold cache). Subsequent runs are fast.

The token-gated tests in the same file additionally require `SLACK_BOT_TOKEN`+`SLACK_TEAM_ID` / `GITHUB_PERSONAL_ACCESS_TOKEN` / `NOTION_API_KEY`.

## Operational notes

- **Subprocess fan-out**: With `MCP_MAX_PROCESSES=200` and idle reap at 10 minutes, a pod with 100 active tenants × 4 servers each lands at ~400 subprocesses *if* every tenant uses every server simultaneously. In practice, idle reap keeps the live count an order of magnitude below the active-tenant count. If memory pressure is observed, lower `MCP_IDLE_REAP_SECONDS`.
- **Failure isolation**: A crashed subprocess is evicted from the pool on the next call so a fresh process spawns automatically. There's no automatic retry — the failing call returns an `MCPToolCallError` to the planner, which decides whether to retry.
- **Credential rotation**: Phase 1 doesn't support multi-key rotation. When you rotate `MCP_ENCRYPTION_KEY`, all stored credentials become unreadable until re-entered. A future revision can layer in a `key_version` column and a multi-key decrypt path.

## What's coming in later phases

- **Phase 3** — extend integration tests with token-gated GitHub + Notion checks (rails are already proven; just creds + canary tests).
- **Phase 4** — Google Drive OAuth2 flow + token refresh (catalog entry already marks `oauth_flow="oauth2"`).
- **Phase 5** — HTTP admin routes (`/api/v1/mcp/connections` etc.) and the `/sources` UI integration.
