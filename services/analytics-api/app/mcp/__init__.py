"""MCP adapter over the agent tool surface (ADS-061)."""

from app.mcp.adapter import PROTOCOL_VERSION, McpAdapter, mcp_name, serve_lines

__all__ = ["PROTOCOL_VERSION", "McpAdapter", "mcp_name", "serve_lines"]
