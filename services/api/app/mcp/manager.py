# services/api/app/mcp/manager.py
"""
High-level facade for the rest of the codebase.

Outside callers (agent nodes, HTTP routes, tests) should reach the MCP
layer ONLY through the singleton exported from this module:

    from app.mcp import mcp_manager
    result = await mcp_manager.call_tool(ctx, "slack.search", {"query": "..."})

The manager owns: catalog→spawn-spec mapping, decryption, pool dispatch,
timeout enforcement, audit emission, and connection-state transitions on
errors. It is intentionally async-method-rich and field-poor — state lives
in the pool and the DB, not here.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from typing import Any, Optional

from app.mcp import storage
from app.mcp.catalog import MCPCatalog
from app.mcp.errors import (
    MCPCapacityError,
    MCPConnectionNotFoundError,
    MCPCryptoError,
    MCPError,
    MCPNotEnabledError,
    MCPServerSpawnError,
    MCPToolCallError,
    MCPToolTimeoutError,
)
from app.mcp.process_pool import MCPProcessPool
from app.mcp.types import (
    MCPConnectionStatus,
    MCPToolDescriptor,
    ToolCallResult,
)

logger = logging.getLogger(__name__)

# Soft import — same rationale as in process_pool.py. Real production paths
# import the SDK; tests inject fakes via configure(_pool=...).
try:
    from mcp import StdioServerParameters
except Exception:  # pragma: no cover
    StdioServerParameters = None  # type: ignore[assignment]


class MCPManager:
    """
    Application-wide singleton. Configure once during lifespan.

    Methods are split into three banks:
      - admin/state:  enable, disable, remove, test, list_connections
      - planning:     list_tools (returns descriptors used by the planner)
      - dispatch:     call_tool (the hot path used by tool_node)

    None of these methods open their own DB sessions on the hot path —
    they accept a session in. The HTTP routes handle session lifecycle;
    the agent path uses the same manager entry but with the AsyncSessionLocal
    convenience wrapper.
    """

    def __init__(self) -> None:
        self._enabled: bool = False
        self._pool: Optional[MCPProcessPool] = None
        self._tool_timeout: int = 30
        # Per-(tenant, server) cached tool listings. Invalidated on evict.
        self._tool_cache: dict[tuple[str, str], list[MCPToolDescriptor]] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────

    def configure(
        self,
        *,
        enabled: bool,
        pool: MCPProcessPool,
        tool_timeout_seconds: int = 30,
    ) -> None:
        """Wire up at lifespan boot. Idempotent for tests."""
        self._enabled = enabled
        self._pool = pool
        self._tool_timeout = tool_timeout_seconds

    @property
    def enabled(self) -> bool:
        return self._enabled and self._pool is not None

    async def shutdown(self) -> None:
        """Drain the pool. Safe to call multiple times."""
        if self._pool is not None:
            await self._pool.stop()
        self._tool_cache.clear()

    # ── Admin / state ────────────────────────────────────────────────────

    async def enable_connection(
        self,
        session,
        *,
        tenant_id: str,
        server_name: str,
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Persist credentials and run an initial health check.

        Returns the row dict. Caller (route) decides the HTTP shape.
        """
        self._require_enabled()
        catalog_entry = MCPCatalog.get(server_name)
        if catalog_entry is None:
            raise MCPConnectionNotFoundError(
                f"unknown MCP server: {server_name}",
                extra={"server_name": server_name},
            )
        # Validate required credentials are present before touching storage.
        missing = [
            k for k in catalog_entry.required_credentials if not credentials.get(k)
        ]
        if missing:
            raise MCPError(
                f"missing required credentials for {server_name}: {', '.join(missing)}",
                extra={"server_name": server_name, "missing": missing},
            )

        row = await storage.upsert(
            session,
            tenant_id=tenant_id,
            server_name=server_name,
            credentials=credentials,
            status=MCPConnectionStatus.PENDING,
        )

        # Health-probe immediately. Failure flips the row to ERROR but we
        # don't raise — caller can show the user the error_message.
        ok, err = await self._probe_health(tenant_id, server_name, credentials)
        new_status = (
            MCPConnectionStatus.ENABLED if ok else MCPConnectionStatus.ERROR
        )
        await storage.set_status(
            session,
            tenant_id=tenant_id,
            server_name=server_name,
            status=new_status,
            error_message=err,
            health_check_now=True,
        )
        row["status"] = new_status.value
        row["error_message"] = err
        return row

    async def disable_connection(
        self, session, *, tenant_id: str, server_name: str
    ) -> bool:
        """Mark DISABLED + reap any live subprocess. Idempotent."""
        self._require_enabled()
        await self._reap(tenant_id, server_name)
        return await storage.set_status(
            session,
            tenant_id=tenant_id,
            server_name=server_name,
            status=MCPConnectionStatus.DISABLED,
        )

    async def remove_connection(
        self, session, *, tenant_id: str, server_name: str
    ) -> bool:
        """Hard-delete the row + reap. Audit log retains history separately."""
        self._require_enabled()
        await self._reap(tenant_id, server_name)
        return await storage.remove(
            session, tenant_id=tenant_id, server_name=server_name
        )

    async def list_connections(
        self, session, *, tenant_id: str
    ) -> list[dict[str, Any]]:
        """All connections for a tenant (any status)."""
        return await storage.list_for_tenant(session, tenant_id)

    async def test_connection(
        self, session, *, tenant_id: str, server_name: str
    ) -> tuple[bool, Optional[str]]:
        """
        Re-probe a stored connection. Updates status + last_health_check.

        Returns (ok, error_message).
        """
        self._require_enabled()
        conn = await storage.get(
            session, tenant_id, server_name, decrypt=True
        )
        if conn is None:
            raise MCPConnectionNotFoundError(
                f"no connection {tenant_id}/{server_name}"
            )
        creds = conn.get("credentials")
        if creds is None:
            return False, "credentials decrypt failed"
        ok, err = await self._probe_health(tenant_id, server_name, creds)
        await storage.set_status(
            session,
            tenant_id=tenant_id,
            server_name=server_name,
            status=(
                MCPConnectionStatus.ENABLED if ok else MCPConnectionStatus.ERROR
            ),
            error_message=err,
            health_check_now=True,
        )
        return ok, err

    # ── Planning ─────────────────────────────────────────────────────────

    async def list_tools(
        self,
        session,
        *,
        tenant_id: str,
        cache: bool = True,
    ) -> list[MCPToolDescriptor]:
        """
        Tools available to this tenant across all enabled MCP servers.

        Result is cached in-memory keyed on (tenant, server). Cache is
        cleared whenever a connection is enabled/disabled/removed or its
        underlying subprocess is evicted.
        """
        if not self.enabled:
            return []
        connections = await storage.list_for_tenant(
            session, tenant_id, only_enabled=True
        )
        descriptors: list[MCPToolDescriptor] = []
        for conn in connections:
            key = (tenant_id, conn["server_name"])
            cached = self._tool_cache.get(key) if cache else None
            if cached is not None:
                descriptors.extend(cached)
                continue
            try:
                # Need decrypted creds for spawn — refetch with decrypt=True.
                full = await storage.get(
                    session, tenant_id, conn["server_name"], decrypt=True
                )
                creds = (full or {}).get("credentials")
                if not creds:
                    continue
                fetched = await self._fetch_tools(
                    tenant_id, conn["server_name"], creds
                )
                self._tool_cache[key] = fetched
                descriptors.extend(fetched)
            except MCPError as e:
                # One server's failure shouldn't drop the others.
                logger.warning(
                    "list_tools failed for %s: %s — skipping",
                    conn["server_name"], e.message,
                )
        return descriptors

    def is_qualified_name(self, name: str) -> bool:
        """`{server}.{tool}` test used by the agent's tool_node."""
        if "." not in name:
            return False
        server, _, _ = name.partition(".")
        return server in MCPCatalog.names()

    # ── Dispatch (hot path) ──────────────────────────────────────────────

    async def call_tool(
        self,
        session,
        *,
        tenant_id: str,
        qualified_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        """
        Run an MCP tool. Hot path used by the agent's tool node.

        Raises:
          MCPNotEnabledError       — feature is off
          MCPConnectionNotFoundError — the server isn't enabled for tenant
          MCPCapacityError         — pool full
          MCPServerSpawnError      — subprocess failed to start
          MCPToolTimeoutError      — exceeded MCP_TOOL_TIMEOUT_SECONDS
          MCPToolCallError         — server reported a tool-level error
        """
        self._require_enabled()
        server_name, _, tool_name = qualified_name.partition(".")
        if not server_name or not tool_name:
            raise MCPToolCallError(
                f"invalid qualified tool name: {qualified_name}",
                extra={"qualified_name": qualified_name},
            )
        catalog_entry = MCPCatalog.get(server_name)
        if catalog_entry is None:
            raise MCPConnectionNotFoundError(
                f"unknown MCP server: {server_name}"
            )
        conn = await storage.get(
            session, tenant_id, server_name, decrypt=True
        )
        if conn is None or conn["status"] != MCPConnectionStatus.ENABLED.value:
            raise MCPConnectionNotFoundError(
                f"server '{server_name}' is not enabled for this tenant",
                extra={"tenant_id": tenant_id, "server_name": server_name},
            )
        creds = conn.get("credentials")
        if creds is None:
            raise MCPCryptoError(
                f"credential decrypt failed for {tenant_id}/{server_name}"
            )

        spawn_spec = self._build_spawn_spec(catalog_entry, creds)
        assert self._pool is not None  # _require_enabled checks
        sess = await self._pool.get_session(tenant_id, server_name, spawn_spec)

        # Bracket the call with a guard so the reaper never tears down a
        # busy entry mid-call.
        guard = await self._pool.with_call((tenant_id, server_name))
        start = time.monotonic()
        try:
            async with guard:
                result = await asyncio.wait_for(
                    sess.call_tool(tool_name, arguments),
                    timeout=self._tool_timeout,
                )
        except asyncio.TimeoutError as e:
            # Eviction: a stuck server should be respawned next call.
            await self._reap(tenant_id, server_name)
            raise MCPToolTimeoutError(
                f"tool {qualified_name} timed out after {self._tool_timeout}s",
                extra={"qualified_name": qualified_name},
            ) from e
        except (MCPCapacityError, MCPServerSpawnError, MCPError):
            raise
        except Exception as e:
            # Subprocess crashed or transport broke. Evict so a fresh process
            # gets created on the next call.
            await self._reap(tenant_id, server_name)
            raise MCPToolCallError(
                f"tool {qualified_name} failed: {e}",
                extra={"qualified_name": qualified_name},
            ) from e

        latency_ms = int((time.monotonic() - start) * 1000)
        return _to_call_result(qualified_name, result, latency_ms)

    # ── Internals ────────────────────────────────────────────────────────

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise MCPNotEnabledError(
                "MCP integration is disabled (set MCP_ENABLED=true and configure key)"
            )

    def _build_spawn_spec(self, entry, credentials: dict[str, Any]):
        """Catalog + creds → StdioServerParameters."""
        if StdioServerParameters is None:
            raise MCPServerSpawnError(
                "MCP SDK not installed: pip install 'mcp>=1.1.0'"
            )
        npx = shutil.which("npx") or "npx"
        env = {
            **os.environ.copy(),  # let server inherit baseline
            **{k: str(v) for k, v in credentials.items() if v is not None},
        }
        return StdioServerParameters(
            command=npx,
            args=["-y", entry.npx_package],
            env=env,
        )

    async def _probe_health(
        self, tenant_id: str, server_name: str, credentials: dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Connect, list_tools, disconnect. Used by enable + test endpoints.

        Bypasses the pool because health checks shouldn't keep a long-lived
        process around; we want a clean ephemeral spawn here.
        """
        catalog_entry = MCPCatalog.get(server_name)
        if catalog_entry is None:
            return False, f"unknown server {server_name}"
        try:
            tools = await self._fetch_tools(tenant_id, server_name, credentials)
            logger.info(
                "mcp health ok tenant=%s server=%s tools=%d",
                tenant_id, server_name, len(tools),
            )
            return True, None
        except MCPError as e:
            return False, e.message
        except Exception as e:  # pragma: no cover — defensive
            return False, str(e)

    async def _fetch_tools(
        self, tenant_id: str, server_name: str, credentials: dict[str, Any]
    ) -> list[MCPToolDescriptor]:
        """Open session via pool, list_tools, namespace, return descriptors."""
        catalog_entry = MCPCatalog.get(server_name)
        if catalog_entry is None:
            return []
        spawn_spec = self._build_spawn_spec(catalog_entry, credentials)
        assert self._pool is not None
        sess = await self._pool.get_session(tenant_id, server_name, spawn_spec)
        list_tools = getattr(sess, "list_tools", None)
        if list_tools is None:
            return []
        result = await asyncio.wait_for(list_tools(), timeout=self._tool_timeout)
        # MCP returns a `ListToolsResult` with `.tools`. Tests pass plain lists.
        raw = getattr(result, "tools", result) or []
        descriptors: list[MCPToolDescriptor] = []
        for t in raw:
            tool_name = getattr(t, "name", None) or t.get("name")
            if not tool_name:
                continue
            description = getattr(t, "description", None) or t.get("description", "")
            schema = getattr(t, "inputSchema", None) or t.get("inputSchema", {})
            descriptors.append(
                MCPToolDescriptor(
                    server_name=server_name,
                    tool_name=tool_name,
                    qualified_name=f"{server_name}.{tool_name}",
                    description=description or "",
                    input_schema=schema or {},
                )
            )
        return descriptors

    async def _reap(self, tenant_id: str, server_name: str) -> None:
        """Evict subprocess + invalidate the cached tool list."""
        if self._pool is not None:
            await self._pool.evict(tenant_id, server_name)
        self._tool_cache.pop((tenant_id, server_name), None)


def _to_call_result(qualified_name: str, raw, latency_ms: int) -> ToolCallResult:
    """
    Convert MCP `CallToolResult` (or test stand-in) into our flat shape.

    The MCP SDK returns `.content` as a list of content blocks, each with
    a `.text` or `.type`. We collapse text blocks into a single string to
    match the rest of our tool dispatch. Non-text blocks are stringified
    via `repr` so they're never silently dropped.
    """
    is_error = bool(getattr(raw, "isError", False))
    blocks = getattr(raw, "content", None)
    if blocks is None and isinstance(raw, dict):
        blocks = raw.get("content")
    if blocks is None:
        text = str(raw)
    else:
        parts: list[str] = []
        for b in blocks:
            t = getattr(b, "text", None) or (b.get("text") if isinstance(b, dict) else None)
            if t:
                parts.append(t)
            else:
                parts.append(repr(b))
        text = "\n".join(parts)
    raw_dict = (
        {"isError": is_error, "content_blocks": len(blocks or [])}
        if not isinstance(raw, dict)
        else raw
    )
    return ToolCallResult(
        qualified_name=qualified_name,
        content=text,
        is_error=is_error,
        latency_ms=latency_ms,
        raw=raw_dict,
    )


# Process-wide singleton. Lifespan calls .configure(); shutdown calls .shutdown().
mcp_manager = MCPManager()
