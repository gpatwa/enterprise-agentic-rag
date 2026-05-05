# services/api/app/mcp/types.py
"""
Public types for the MCP layer. Frozen dataclasses + a small enum.

These cross the public boundary (routes, agent nodes, tests). Keep them
JSON-serialisable and dependency-free so the surface stays stable when
the underlying mcp/anthropic SDK rev-bumps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class MCPConnectionStatus(str, Enum):
    """
    Lifecycle states for a tenant's connection to an MCP server.

    Transitions:
        PENDING  → ENABLED         (creds saved, first health check passed)
        PENDING  → ERROR           (creds saved, health check failed)
        ENABLED  → ERROR           (a tool call surfaced auth/quota failure)
        ERROR    → ENABLED         (admin re-tested successfully)
        ENABLED  → DISABLED        (admin paused — keeps row + creds)
        any      → (deleted)       (admin removed via DELETE — row gone)
    """

    PENDING = "pending"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(frozen=True)
class MCPCatalogEntry:
    """
    Static metadata about a *known* MCP server — what we ship support for.

    `npx_package` is the source of truth: spawning the subprocess shells out to
    `npx -y <npx_package>`. `required_credentials` lists env vars the server
    expects at process start; the manager pulls these from the encrypted
    connection row and injects them into the child's env.

    `oauth_flow` is None for PAT-style servers (Slack/GitHub/Notion). When
    set to "oauth2", credentials are managed by the OAuth callback route
    instead of a static-token form (Phase 4 — Drive).
    """

    server_name: str
    display_name: str
    description: str
    npx_package: str
    required_credentials: tuple[str, ...]
    oauth_flow: Optional[str] = None  # None | "oauth2"
    docs_url: Optional[str] = None


@dataclass(frozen=True)
class MCPToolDescriptor:
    """
    A single tool exposed by an MCP server, after namespacing.

    `qualified_name` is what the planner sees and what `tool_node` dispatches
    on — always `{server_name}.{tool_name}`. `input_schema` is the raw JSON
    Schema the server advertised; we forward it verbatim to the planner.
    """

    server_name: str
    tool_name: str
    qualified_name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallResult:
    """
    Outcome of an MCP tool call. `content` is the (possibly multi-block) text
    output; `is_error` lets callers distinguish server-reported errors from
    successful results without inspecting strings. `latency_ms` is captured
    inside the manager so audit logs stay accurate even if callers forget.
    """

    qualified_name: str
    content: str
    is_error: bool
    latency_ms: int
    raw: Optional[dict[str, Any]] = None  # original MCP response, opaque
