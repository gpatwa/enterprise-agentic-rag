# services/api/app/agents/nodes/context_enricher.py
"""
LangGraph Node: Context Enricher.

Runs between the retriever and responder nodes.
Fetches supplementary context from all enabled context layers
and adds it to the agent state for the responder to use.
"""
import logging
from typing import Dict

from langchain_core.runnables import RunnableConfig

from app.agents.state import AgentState

logger = logging.getLogger(__name__)

# Late-initialised assembler — set by main.py lifespan
_assembler = None


def set_assembler(assembler):
    """Called once during app startup to inject the ContextAssembler."""
    global _assembler
    _assembler = assembler


async def context_enricher_node(state: AgentState, config: RunnableConfig) -> Dict:
    """
    Fetches supplementary context from all enabled context layers.

    Reads retrieved documents from state, queries context layers in parallel,
    and returns assembled context string for injection into the LLM prompt.
    """
    if _assembler is None:
        logger.warning("Context assembler not initialized, skipping enrichment")
        return {"context_layers": ""}

    configurable = config.get("configurable", {})
    tenant_id = configurable.get("tenant_id", "default")
    user_role = configurable.get("user_role", "all")

    documents = state.get("documents", [])
    query = state["current_query"]

    try:
        context_text = await _assembler.assemble(
            query=query,
            documents=documents,
            tenant_id=tenant_id,
            user_role=user_role,
        )

        if context_text:
            logger.info(
                f"Context enricher: assembled {len(context_text)} chars "
                f"for query '{query[:50]}...' (tenant={tenant_id})"
            )
        else:
            logger.debug(f"Context enricher: no context found for '{query[:50]}...'")

        return {"context_layers": context_text}

    except Exception as e:
        logger.error(f"Context enricher failed: {e}")
        return {"context_layers": ""}
