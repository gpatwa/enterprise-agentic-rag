# services/api/app/agents/graph.py
from langgraph.graph import END, StateGraph

from app.agents.nodes.data_analytics import data_analytics_node
from app.agents.nodes.evaluator import evaluator_node, retry_node
from app.agents.nodes.planner import planner_node, step_advance_node
from app.agents.nodes.responder import generate_node
from app.agents.nodes.retriever import retrieve_node
from app.agents.nodes.tool import tool_node
from app.agents.state import AgentState
from app.config import settings

# Maximum ReAct iterations before forcing a response
MAX_ITERATIONS = 3

# Self-evaluation: accept if score >= threshold
EVAL_THRESHOLD = 3


def route_after_planner(state: AgentState) -> str:
    """Conditional edge: route based on planner's action decision."""
    if state.get("iteration_count", 0) > MAX_ITERATIONS:
        return "responder"

    action = state.get("action", "retrieve")
    if action == "direct_answer":
        return "responder"
    elif action == "tool_use":
        return "tool_node"
    elif action == "data_query" and settings.DATA_ANALYTICS_ENABLED:
        return "data_analytics"
    else:  # "retrieve" or fallback
        return "retriever"


def route_after_responder(state: AgentState) -> str:
    """After responder: check if multi-step plan has more steps, else evaluate.

    Latency optimization: skip the evaluator LLM call when retrieval returned
    documents (high-confidence answers).  Controlled via EVALUATOR_ENABLED and
    EVALUATOR_SKIP_WITH_CONTEXT config flags.
    """
    current_step_index = state.get("current_step_index", -1)
    plan_steps = state.get("plan_steps", [])

    if current_step_index >= 0 and current_step_index < len(plan_steps) - 1:
        return "step_advance"

    # Skip evaluator when documents were found (configurable)
    if settings.EVALUATOR_SKIP_WITH_CONTEXT and state.get("documents"):
        return "end"

    # Master kill-switch for evaluator
    if not settings.EVALUATOR_ENABLED:
        return "end"

    return "evaluator"


def route_after_evaluator(state: AgentState) -> str:
    """Accept the answer or retry once if quality is low."""
    score = state.get("eval_score", 0)
    retry_count = state.get("retry_count", 0)

    # Accept: evaluation skipped/errored, score acceptable, or already retried
    if score == 0 or score >= EVAL_THRESHOLD or retry_count >= 1:
        return "end"
    return "retry"


# Build the graph
workflow = StateGraph(AgentState)

# 1. Define Nodes
workflow.add_node("planner", planner_node)
workflow.add_node("retriever", retrieve_node)
workflow.add_node("responder", generate_node)
workflow.add_node("tool_node", tool_node)
workflow.add_node("evaluator", evaluator_node)
workflow.add_node("retry", retry_node)
workflow.add_node("step_advance", step_advance_node)
workflow.add_node("data_analytics", data_analytics_node)

# 2. Define Edges
workflow.set_entry_point("planner")

# Conditional routing after planner: retrieve / direct_answer / tool_use
_planner_edges = {
    "retriever": "retriever",
    "responder": "responder",
    "tool_node": "tool_node",
    "data_analytics": "data_analytics",
}

workflow.add_conditional_edges("planner", route_after_planner, _planner_edges)
workflow.add_edge("data_analytics", "responder")

# After retrieval → context enrichment (if enabled) → respond
if settings.CONTEXT_LAYERS_ENABLED:
    from app.agents.nodes.context_enricher import context_enricher_node
    workflow.add_node("context_enricher", context_enricher_node)
    workflow.add_edge("retriever", "context_enricher")
    workflow.add_edge("context_enricher", "responder")
else:
    workflow.add_edge("retriever", "responder")

# After tool execution → back to planner (ReAct loop)
workflow.add_edge("tool_node", "planner")

# After response → evaluate (or advance multi-step plan, or end if evaluator skipped)
workflow.add_conditional_edges("responder", route_after_responder, {
    "evaluator": "evaluator",
    "step_advance": "step_advance",
    "end": END,
})

# Step advance → back to planner for next step
workflow.add_edge("step_advance", "planner")

# After evaluation → accept (END) or retry
workflow.add_conditional_edges("evaluator", route_after_evaluator, {
    "end": END,
    "retry": "retry",
})

# Retry → re-retrieve with refined query
workflow.add_edge("retry", "retriever")

# 3. Compile the Graph
agent_app = workflow.compile()
