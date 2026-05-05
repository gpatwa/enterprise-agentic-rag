#!/usr/bin/env python3
"""
Enable an MCP connection for a tenant from the command line.

Lets you wire up Slack/GitHub/Notion/Drive without standing up the HTTP
admin routes (which land in Phase 5). Reads credentials interactively or
from env, runs the manager's full enable_connection flow (Fernet-encrypt
→ persist → health-probe), and prints the resulting status.

Usage examples
--------------
    # Interactive — prompts for any required credential
    python -m services.api.scripts.mcp_enable --tenant default --server slack

    # From env (CI / scripts)
    SLACK_BOT_TOKEN=xoxb-... SLACK_TEAM_ID=T0... \\
        python -m services.api.scripts.mcp_enable \\
            --tenant default --server slack --from-env

    # List enabled connections for a tenant
    python -m services.api.scripts.mcp_enable --tenant default --list

    # Disable a connection (keeps row + creds, but won't dispatch)
    python -m services.api.scripts.mcp_enable --tenant default --server slack --disable

Pre-reqs
--------
- DATABASE_URL set, MCP_ENABLED=true, MCP_ENCRYPTION_KEY exported (or
  reachable via the secrets vault).
- Node + npx on PATH (the health probe spawns the MCP server).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys


def _resolve_credentials(
    server_name: str, from_env: bool, prompt: bool
) -> dict[str, str]:
    """Pull required credentials from env or prompt interactively."""
    from app.mcp.catalog import MCPCatalog

    entry = MCPCatalog.get(server_name)
    if entry is None:
        sys.exit(f"unknown server '{server_name}' — known: {sorted(MCPCatalog.names())}")
    creds: dict[str, str] = {}
    for key in entry.required_credentials:
        env_val = os.environ.get(key)
        if from_env:
            if not env_val:
                sys.exit(f"missing env var {key}")
            creds[key] = env_val
        elif prompt:
            shown = env_val or ""
            entered = getpass.getpass(
                f"{key}{f' [press enter to use ${key}]' if shown else ''}: "
            )
            creds[key] = entered or shown
            if not creds[key]:
                sys.exit(f"missing credential {key}")
        else:
            creds[key] = env_val or ""
    return creds


async def _bootstrap_mcp() -> None:
    """Init secrets vault → cipher → pool → manager (mirrors lifespan)."""
    from app.clients.secrets.factory import create_secrets_client
    from app.config import settings
    from app.mcp.crypto import init_cipher
    from app.mcp.manager import mcp_manager
    from app.mcp.process_pool import MCPProcessPool

    secrets = create_secrets_client(
        settings.SECRETS_PROVIDER,
        region=settings.AWS_REGION,
        prefix=settings.SECRETS_PREFIX,
        vault_url=settings.AZURE_KEY_VAULT_URL,
    )
    key = settings.MCP_ENCRYPTION_KEY or os.environ.get("MCP_ENCRYPTION_KEY")
    if not key:
        key = await secrets.get_secret("MCP_ENCRYPTION_KEY")
    if not key:
        sys.exit("MCP_ENCRYPTION_KEY missing (env or secrets vault)")
    init_cipher(key)

    pool = MCPProcessPool(
        max_processes=settings.MCP_MAX_PROCESSES,
        idle_seconds=None,
        tool_timeout_seconds=settings.MCP_TOOL_TIMEOUT_SECONDS,
    )
    mcp_manager.configure(
        enabled=True,
        pool=pool,
        tool_timeout_seconds=settings.MCP_TOOL_TIMEOUT_SECONDS,
    )

    # DB engine — the manager talks to storage which talks to AsyncSessionLocal
    from app.memory.postgres import init_engine

    init_engine()


async def _do_enable(tenant: str, server: str, creds: dict[str, str]) -> None:
    from app.mcp.manager import mcp_manager
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        sys.exit("DB engine not initialized (set DATABASE_URL)")

    async with AsyncSessionLocal() as session:
        row = await mcp_manager.enable_connection(
            session, tenant_id=tenant, server_name=server, credentials=creds
        )
    print(f"server={server} status={row['status']}")
    if row.get("error_message"):
        print(f"  error: {row['error_message']}")


async def _do_disable(tenant: str, server: str) -> None:
    from app.mcp.manager import mcp_manager
    from app.memory.postgres import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        ok = await mcp_manager.disable_connection(
            session, tenant_id=tenant, server_name=server
        )
    print(f"disabled={ok}")


async def _do_list(tenant: str) -> None:
    from app.mcp.manager import mcp_manager
    from app.memory.postgres import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        rows = await mcp_manager.list_connections(session, tenant_id=tenant)
    if not rows:
        print(f"(no connections for tenant {tenant})")
        return
    for r in rows:
        print(
            f"  {r['server_name']:10s} status={r['status']:10s} "
            f"last_check={r['last_health_check']} err={r['error_message']}"
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Enable / disable / list MCP connections.")
    p.add_argument("--tenant", required=True)
    p.add_argument("--server", help="catalog name (slack/github/notion/gdrive)")
    p.add_argument("--from-env", action="store_true",
                   help="read required credentials from env vars (CI mode)")
    p.add_argument("--no-prompt", action="store_true",
                   help="don't prompt; fail if creds aren't in env")
    p.add_argument("--disable", action="store_true",
                   help="disable instead of enable")
    p.add_argument("--list", action="store_true",
                   help="list all connections for the tenant")
    args = p.parse_args()

    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    await _bootstrap_mcp()
    if args.list:
        await _do_list(args.tenant)
        return
    if not args.server:
        sys.exit("--server required (or use --list)")
    if args.disable:
        await _do_disable(args.tenant, args.server)
        return
    creds = _resolve_credentials(
        args.server,
        from_env=args.from_env,
        prompt=not args.no_prompt and not args.from_env,
    )
    await _do_enable(args.tenant, args.server, creds)


if __name__ == "__main__":
    main()
