# services/api/app/agents/nodes/tool.py
"""
Tool dispatcher node.

Two dispatch backends, both reachable from the same LangGraph node:

  1. Static `TOOL_DISPATCH` — calculator, vector_search, graph_search,
     code_sandbox, web_search. Hard-wired in this file.
  2. MCP tools — qualified names of the form `{server}.{tool}` are
     forwarded through `mcp_manager.call_tool()` after a tenant-scoped
     lookup. The list of available MCP tools per tenant is built by
     `app.tools.registry.get_tools_for_tenant()` for the planner.

The two backends never overlap: MCP tool names contain a dot, static
tool names do not. A single chooser branches on `mcp_manager.is_qualified_name()`
to pick the path.

Concurrency / failure
---------------------
- MCP failures are converted to error strings the planner can read,
  matching the existing static-tool error contract. The agent graph
  decides whether to retry or surface to the user.
- Audit logging happens at the route level (chat.py); we don't double-log
  here. Per-tool-call MCP audit (event_type=mcp.tool_call) is emitted by
  this node since the route doesn't see individual tool dispatches.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.state import AgentState
from app.tools.calculator import calculate
from app.tools.graph_search import search_graph_tool
from app.tools.sandbox import run_python_code
from app.tools.vector_search import search_vector_tool
from app.tools.web_search import web_search_tool

logger = logging.getLogger(__name__)

# Dispatch table mapping tool names to their handler functions.
# Sync tools (calculator) are wrapped in the execution logic below.
TOOL_DISPATCH = {
    "calculator": calculate,
    "vector_search": search_vector_tool,
    "graph_search": search_graph_tool,
    "code_sandbox": run_python_code,
    "web_search": web_search_tool,
}


async def tool_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    Executes the tool selected by the planner.

    Reads tool_name + tool_input from state. If `tool_name` is namespaced
    (`{server}.{tool}`) and the manager recognises the prefix, dispatches
    through MCP. Otherwise falls through to the static dispatch table.
    """
    tool_name = state.get("tool_name", "")
    tool_input = state.get("tool_input", "")

    if not tool_name:
        logger.warning("Tool node called with no tool_name in state")
        return {
            "tool_result": "No tool was selected.",
            "messages": [{"role": "assistant", "content": "[Tool] No tool was selected."}],
        }

    # ── MCP path ─────────────────────────────────────────────────────────
    # Imported lazily so the agent module stays importable when MCP is off
    # (avoids forcing the SDK install in dev/test setups that don't use it).
    from app.mcp import mcp_manager

    if mcp_manager.is_qualified_name(tool_name):
        result = await _dispatch_mcp(tool_name, tool_input, config)
    else:
        result = await _dispatch_static(tool_name, tool_input)

    logger.info("Tool %s completed, result length: %d", tool_name, len(str(result)))
    return {
        "tool_result": result,
        "messages": [{"role": "assistant", "content": f"[Tool: {tool_name}] {result}"}],
    }


# ── Dispatch helpers ──────────────────────────────────────────────────────


async def _dispatch_static(tool_name: str, tool_input: str) -> str:
    """Existing in-process tools. Returns a string result; never raises."""
    handler = TOOL_DISPATCH.get(tool_name)
    if not handler:
        logger.error("Unknown tool requested: %s", tool_name)
        return f"Unknown tool: {tool_name}"
    logger.info("Executing tool: %s with input: %s", tool_name, tool_input[:100])
    try:
        result = handler(tool_input)
        if asyncio.iscoroutine(result):
            result = await result
        return result
    except Exception as e:
        logger.error("Tool execution failed: %s — %s", tool_name, e)
        return f"Tool error ({tool_name}): {e}"


async def _dispatch_mcp(
    qualified_name: str, tool_input: str, config: RunnableConfig
) -> str:
    """
    Run a `{server}.{tool}` call through the MCP manager.

    Tenant id comes from the LangGraph `configurable` block (same pattern
    as the retriever node). The agent's planner currently passes a single
    string `tool_input`; MCP servers expect a JSON object. We accept both:
      - `{"key": "value", ...}` parsed JSON wins
      - any other string falls back to `{"query": "<input>"}`
    Servers that need different field names will surface a clear error.
    """
    from app.audit import manager as audit_mgr  # local import to avoid cycle
    from app.auth.tenant import DEFAULT_TENANT_ID
    from app.mcp import (
        MCPError,
        mcp_manager,
    )
    from app.memory.postgres import AsyncSessionLocal

    configurable = config.get("configurable", {}) if config else {}
    tenant_id = configurable.get("tenant_id") or DEFAULT_TENANT_ID
    user_id = configurable.get("user_id") or "agent"
    role = configurable.get("role")
    arguments = _parse_arguments(tool_input)

    if AsyncSessionLocal is None:
        # MCP requires DB for the connection lookup. Without it, fail clean.
        return f"Tool error ({qualified_name}): database unavailable"

    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            result = await mcp_manager.call_tool(
                session,
                tenant_id=tenant_id,
                qualified_name=qualified_name,
                arguments=arguments,
            )
        latency_ms = int((time.monotonic() - start) * 1000)
        # Best-effort audit. Never blocks the request path on failure.
        await audit_mgr.log_event(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            event_type="mcp.tool_call",
            duration_ms=latency_ms,
            sources_used=[qualified_name],
            extra={
                "qualified_name": qualified_name,
                "is_error": result.is_error,
                "argument_keys": sorted(arguments.keys()),
                "content_length": len(result.content),
            },
        )
        return result.content if not result.is_error else f"Tool error ({qualified_name}): {result.content}"
    except MCPError as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        await audit_mgr.log_event(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            event_type="mcp.tool_call",
            status_code=502,
            duration_ms=latency_ms,
            sources_used=[qualified_name],
            extra={"qualified_name": qualified_name, **e.to_dict()},
        )
        logger.warning("MCP tool failed %s: %s", qualified_name, e.message)
        return f"Tool error ({qualified_name}): {e.message}"
    except Exception as e:  # pragma: no cover — defensive
        logger.error("MCP dispatch crashed %s: %s", qualified_name, e, exc_info=True)
        return f"Tool error ({qualified_name}): unexpected failure"


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """
    Best-effort string→dict for the planner's tool_input.

    Three accepted shapes:
      - dict (already structured) — used as-is
      - JSON string → parsed
      - anything else → wrapped as {"query": "<str>"}
    """
    import json

    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {"query": s}
    return {"query": str(raw)}
