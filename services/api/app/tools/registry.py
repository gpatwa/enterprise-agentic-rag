# services/api/app/tools/registry.py
"""
Tool registry — what the planner can choose from.

Two layers:
  1. STATIC `TOOL_REGISTRY` — built-in tools always available.
  2. Dynamic per-tenant view via `get_tools_for_tenant()` — merges the
     static set with MCP tools the tenant has enabled.

The planner prompt reads through `get_tool_descriptions()` (static-only,
fast) for default flows and `format_tool_descriptions(tools)` for the
per-tenant case. Keeping the static-only path means non-MCP deployments
pay zero overhead.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolSchema(BaseModel):
    """Schema describing a tool available to the planning agent."""

    name: str
    description: str
    parameter_name: str
    parameter_description: str


TOOL_REGISTRY: dict[str, ToolSchema] = {
    "calculator": ToolSchema(
        name="calculator",
        description="Evaluate a mathematical expression. Use for arithmetic, unit conversions, percentages.",
        parameter_name="expression",
        parameter_description="A math expression like '2 + 2' or '15% of 200'",
    ),
    "vector_search": ToolSchema(
        name="vector_search",
        description="Search internal documents by semantic similarity. Use when user asks to find or look up specific documents.",
        parameter_name="query",
        parameter_description="The search query to find relevant documents",
    ),
    "graph_search": ToolSchema(
        name="graph_search",
        description="Search the knowledge graph for entity relationships. Use when user asks about connections between people, orgs, or concepts.",
        parameter_name="query",
        parameter_description="A question about entity relationships",
    ),
    "code_sandbox": ToolSchema(
        name="code_sandbox",
        description="Execute Python code in an isolated sandbox. Use for data analysis, complex calculations, or code generation.",
        parameter_name="code",
        parameter_description="Python code to execute",
    ),
    "web_search": ToolSchema(
        name="web_search",
        description="Search the internet for current information. Use for recent events or public information not in internal documents.",
        parameter_name="query",
        parameter_description="The search query",
    ),
}


def get_tool_descriptions() -> str:
    """Format static tool schemas for inclusion in the planner prompt."""
    return format_tool_descriptions(list(TOOL_REGISTRY.values()))


def format_tool_descriptions(tools: list[ToolSchema]) -> str:
    """Format any list of tool schemas (static + MCP) into the planner string."""
    return "\n".join(
        f"- {t.name}: {t.description} "
        f"(parameter: {t.parameter_name} — {t.parameter_description})"
        for t in tools
    )


async def get_tools_for_tenant(
    tenant_id: str, *, db_session=None
) -> list[ToolSchema]:
    """
    Static + MCP tools the planner should see for this tenant.

    Returns the static set even if MCP is disabled or fails, so the planner
    is never empty. MCP failures are logged but never raised — the planner
    proceeds with the static set.

    `db_session` is optional; when omitted, a short-lived session is opened
    (cheap; we're already on a Postgres connection-pooled async setup).
    """
    static = list(TOOL_REGISTRY.values())

    try:
        from app.mcp import mcp_manager  # lazy: avoid forcing dep when off
    except Exception as e:
        logger.debug("MCP module not importable: %s", e)
        return static

    if not mcp_manager.enabled:
        return static

    try:
        descriptors = await _list_mcp_tools(tenant_id, db_session)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("MCP list_tools failed for tenant %s: %s", tenant_id, e)
        return static

    mcp_schemas = [
        ToolSchema(
            name=d.qualified_name,
            description=d.description or f"MCP tool {d.qualified_name}",
            parameter_name="input",
            parameter_description=(
                "JSON object matching the tool's input schema, "
                "or a plain string used as `query`."
            ),
        )
        for d in descriptors
    ]
    return static + mcp_schemas


async def _list_mcp_tools(tenant_id: str, db_session) -> list:
    """Helper that owns the optional session lifecycle."""
    from app.mcp import mcp_manager
    from app.memory.postgres import AsyncSessionLocal

    if db_session is not None:
        return await mcp_manager.list_tools(db_session, tenant_id=tenant_id)
    if AsyncSessionLocal is None:
        return []
    async with AsyncSessionLocal() as session:
        return await mcp_manager.list_tools(session, tenant_id=tenant_id)
