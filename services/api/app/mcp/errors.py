# services/api/app/mcp/errors.py
"""
Typed exception hierarchy for MCP.

Why a hierarchy: the agent loop, HTTP routes, and tests each need to make
*different* decisions on different error classes (e.g. retry the call vs
return user-facing message vs alert ops). A flat `MCPError` would force
string-matching, which is fragile.

Convention: every exception carries `code` (stable string for audit and
client error responses) and accepts an optional `extra` dict for ad-hoc
diagnostic context (server_name, tenant_id, latency_ms, etc.). Don't put
secrets in `extra` — it's logged and may surface in error responses.
"""
from __future__ import annotations

from typing import Any, Optional


class MCPError(Exception):
    """Base for every MCP-originating error. Catch this in route handlers."""

    code: str = "mcp.error"

    def __init__(self, message: str, *, extra: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra or {}

    def to_dict(self) -> dict[str, Any]:
        """Stable JSON shape for HTTP responses + audit."""
        return {"code": self.code, "message": self.message, "extra": self.extra}


class MCPNotEnabledError(MCPError):
    """Raised when MCP_ENABLED=False or the master key is missing."""

    code = "mcp.not_enabled"


class MCPConnectionNotFoundError(MCPError):
    """No (tenant, server) row in mcp_connections, or status != enabled."""

    code = "mcp.connection_not_found"


class MCPServerSpawnError(MCPError):
    """Subprocess failed to start, exited early, or never reported ready."""

    code = "mcp.spawn_failed"


class MCPToolCallError(MCPError):
    """The MCP server accepted the call but returned an error result."""

    code = "mcp.tool_call_failed"


class MCPToolTimeoutError(MCPError):
    """A tool call exceeded MCP_TOOL_TIMEOUT_SECONDS."""

    code = "mcp.tool_call_timeout"


class MCPCapacityError(MCPError):
    """Pool is at MCP_MAX_PROCESSES and refusing to spawn another."""

    code = "mcp.capacity_exceeded"


class MCPCryptoError(MCPError):
    """Encryption / decryption of stored credentials failed."""

    code = "mcp.crypto_error"
