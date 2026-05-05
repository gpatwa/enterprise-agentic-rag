# services/api/app/mcp/__init__.py
"""
Model Context Protocol (MCP) integration.

Architecture overview
---------------------
Layers, top to bottom (outer depends on inner):

    routes/mcp.py              ← HTTP surface (Phase 5)
        │
        ▼
    mcp/manager.py             ← MCPManager facade — single import point
        │                        for everything else (agents, routes, tests).
        ├──► mcp/process_pool.py    Lazy-spawn + idle-reap of (tenant, server)
        │                            stdio subprocesses, asyncio-locked.
        ├──► mcp/storage.py          Encrypted persistence of MCPConnection rows.
        ├──► mcp/crypto.py           Fernet wrapper over the master key.
        ├──► mcp/catalog.py          Static metadata for known servers
        │                            (slack, github, notion, gdrive).
        ├──► mcp/types.py            Public dataclasses + protocol types.
        ├──► mcp/errors.py           Typed exception hierarchy.
        └──► mcp/models.py           SQLAlchemy MCPConnection model.

Public API (re-exported here for ergonomic import sites):

    from app.mcp import mcp_manager, MCPError, ToolCallResult, MCPCatalog

Anything outside this package SHOULD import only from `app.mcp` (this
module). Internal modules stay private.
"""
from __future__ import annotations

from app.mcp.catalog import MCPCatalog  # noqa: F401
from app.mcp.errors import (  # noqa: F401
    MCPCapacityError,
    MCPConnectionNotFoundError,
    MCPCryptoError,
    MCPError,
    MCPNotEnabledError,
    MCPServerSpawnError,
    MCPToolCallError,
    MCPToolTimeoutError,
)

# Public manager singleton — initialised by lifespan, used by agents/routes.
from app.mcp.manager import mcp_manager  # noqa: F401
from app.mcp.types import (  # noqa: F401
    MCPCatalogEntry,
    MCPConnectionStatus,
    MCPToolDescriptor,
    ToolCallResult,
)
