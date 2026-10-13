"""A Model Context Protocol (JSON-RPC 2.0) adapter over the agent tool surface (ADS-061).

The adapter is transport-neutral and owns no authority. It authenticates every message from a bearer token supplied by the
transport (never by a tool argument), resolves it to an identity with `IdentityResolver` on *each* request, and hands the call
to the same `AgentToolSurface` (and so the same `GovernedAnalyzeService`, graph, and audit) as every other caller. It imports
no store, gateway, or compiler, which a test enforces.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from app.agent_tools import AgentToolSurface
from app.security import AuthenticationError, IdentityResolver
from packages.platform_contracts.agent_tools import TOOL_CATALOG_VERSION, TOOLS, ToolCall

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "compass-analytics"
MAX_MESSAGE_BYTES = 65_536
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
UNAUTHENTICATED = -32001


def mcp_name(tool: str) -> str:
    """MCP tool names use letters, digits, underscore, and hyphen; the catalogue uses a dot."""
    return tool.replace(".", "_")


_BY_MCP_NAME = {mcp_name(spec.name): spec.name for spec in TOOLS}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class McpAdapter:
    def __init__(self, surface: AgentToolSurface, resolver: IdentityResolver) -> None:
        self.surface, self.resolver = surface, resolver

    def handle(self, token: str | None, raw: str | bytes | dict[str, Any]) -> dict[str, Any] | None:
        """Handle one JSON-RPC message. Returns the response, or None for a notification."""
        if isinstance(raw, (str, bytes)):
            if len(raw) > MAX_MESSAGE_BYTES:
                return _error(None, INVALID_REQUEST, "message too large")
            try:
                message = json.loads(raw)
            except ValueError:
                return _error(None, PARSE_ERROR, "parse error")
        else:
            message = raw
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "invalid request")  # batches are not supported
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str) or (request_id is not None and not isinstance(request_id, (str, int))):
            return _error(
                request_id if isinstance(request_id, (str, int)) else None, INVALID_REQUEST, "invalid request"
            )
        is_notification = "id" not in message
        try:
            identity = self.resolver.resolve(token or "")
        except AuthenticationError:
            if self.surface.audit is not None:
                self.surface.audit.record_denied(transport="mcp", reason="authentication_failed")
            return None if is_notification else _error(request_id, UNAUTHENTICATED, "unauthenticated")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return None if is_notification else _error(request_id, INVALID_PARAMS, "invalid params")
        if is_notification:
            return None  # notifications/initialized, notifications/cancelled, and the like need no reply
        if method == "initialize":
            return self._result(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": TOOL_CATALOG_VERSION},
                },
            )
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(request_id, {"tools": self._tools()})
        if method == "tools/call":
            return self._call(identity, request_id, params)
        return _error(request_id, METHOD_NOT_FOUND, "method not found")

    def _call(self, identity, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        tool = _BY_MCP_NAME.get(name) if isinstance(name, str) else None
        if tool is None or not isinstance(arguments, dict):
            return _error(request_id, INVALID_PARAMS, "unknown tool or invalid arguments")
        result = self.surface.call(identity, ToolCall(tool=tool, arguments=arguments), transport="mcp")
        structured = json.loads(result.model_dump_json())
        return self._result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(structured, separators=(",", ":"))}],
                "structuredContent": structured,
                "isError": not result.ok,
            },
        )

    @staticmethod
    def _tools() -> list[dict[str, Any]]:
        from packages.platform_contracts.agent_tools import ARGUMENT_MODELS

        return [
            {
                "name": mcp_name(spec.name),
                "title": spec.title,
                "description": spec.description,
                "inputSchema": ARGUMENT_MODELS[spec.name].model_json_schema(),
                "annotations": {
                    "readOnlyHint": spec.effect == "read",
                    "destructiveHint": False,
                    "idempotentHint": spec.effect == "read" or spec.requires_idempotency_key,
                    "openWorldHint": False,
                },
            }
            for spec in TOOLS
        ]

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve_lines(adapter: McpAdapter, token: str | None, lines: Iterable[str]) -> Iterator[str]:
    """Line-delimited JSON-RPC (the stdio framing): one response line per request, none for notifications.

    The token is the transport's credential (for stdio, taken from the process environment by the launcher), never a field
    of any message.
    """
    for line in lines:
        if not line.strip():
            continue
        response = adapter.handle(token, line)
        if response is not None:
            yield json.dumps(response, separators=(",", ":"))
