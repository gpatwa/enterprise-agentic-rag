# services/api/app/agents/nodes/planner.py
import hashlib
import json as json_lib
import logging

from app.agents.json_utils import extract_json
from app.agents.state import AgentState
from app.cache.redis import redis_client
from app.clients.ray_llm import llm_client
from app.config import settings
from app.tools.registry import get_tool_descriptions

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a RAG Planning Agent.
Analyze the User Query and Conversation History to decide the next step.

Available tools:
{tool_descriptions}

Decision rules (in priority order):
1. "direct_answer" — ONLY for greetings ("hi", "hello", "thanks"), small talk, or when a Tool Result is already present and sufficient to answer. NEVER use this for factual questions.
2. "data_query" — for quantitative business questions answerable from structured data: revenue, orders, sales, payments, customers, sellers, reviews, delivery, trends, averages, totals, top/bottom rankings. Use this when the question asks for numbers, metrics, or data analysis.
3. "retrieve" — DEFAULT for any question about people, companies, products, events, processes, or facts. Always search internal documents first.
4. "tool_use" — when the user explicitly needs a calculation, code execution, or web search for current events / public information not in internal docs.
5. "multi_step" — complex queries needing multiple steps (e.g. "Compare X with Y" needs retrieval + web search + synthesis).

IMPORTANT: When in doubt, choose "retrieve". Only use "direct_answer" for non-questions.
If a Tool Result is already present, decide whether to answer directly ("direct_answer") or take another action.

For single-step queries (most queries), output ONLY valid JSON:
{{
    "action": "retrieve" | "direct_answer" | "tool_use" | "data_query",
    "refined_query": "The standalone search query",
    "reasoning": "Why you chose this action",
    "tool_name": "name from available tools (required if action is tool_use, omit otherwise)",
    "tool_input": "parameter value for the tool (required if action is tool_use, omit otherwise)"
}}

For complex multi-step queries, output ONLY valid JSON:
{{
    "action": "multi_step",
    "reasoning": "Why this needs multiple steps",
    "steps": [
        {{"action": "retrieve", "query": "search query for step 1", "tool_name": "", "tool_input": ""}},
        {{"action": "tool_use", "query": "what this step does", "tool_name": "web_search", "tool_input": "search query"}},
        {{"action": "respond", "query": "synthesize the results", "tool_name": "", "tool_input": ""}}
    ]
}}"""


_GREETINGS = frozenset({
    "hi", "hello", "hey", "thanks", "thank you", "bye", "goodbye",
    "good morning", "good afternoon", "good evening", "howdy",
})
_QUESTION_PREFIXES = (
    "what", "how", "why", "when", "where", "who", "which",
    "explain", "describe", "tell me", "show me", "list", "define",
    "summarize", "compare",
)
_DATA_KEYWORDS = frozenset({
    "revenue", "orders", "sales", "payments", "customers", "sellers",
    "reviews", "delivery", "shipping", "average", "total", "trend",
    "month", "quarter", "year", "top", "bottom", "best", "worst",
    "how many", "how much", "count", "sum", "growth", "decline",
    "category", "product", "rating", "score", "payment",
})


def _fast_classify(query: str, has_tool_result: bool) -> str | None:
    """
    Rule-based fast classification for obvious intent patterns.
    Returns an action string or None if the query is ambiguous (fall through to LLM).
    """
    q = query.strip().lower().rstrip("!.")

    # If we already have a tool result, direct answer
    if has_tool_result:
        return "direct_answer"

    # Greetings / small talk — no retrieval needed
    if q in _GREETINGS:
        return "direct_answer"

    # Data analytics queries — quantitative business questions. The graph
    # decides whether the analytics node is enabled; classification can still
    # identify the user's intent.
    data_hits = sum(1 for kw in _DATA_KEYWORDS if kw in q)
    if data_hits >= 2:
        return "data_query"

    # Clear question patterns → retrieve from knowledge base
    if "?" in q or q.startswith(_QUESTION_PREFIXES):
        return "retrieve"

    return None  # Ambiguous, use LLM


async def planner_node(state: AgentState) -> dict:
    """
    Decides the path through the LangGraph.
    Returns action field used by conditional edges for routing.
    Supports both single-step and multi-step planning.

    Latency optimizations:
    - Fast-classify: skip LLM for obvious intents (greetings, questions)
    - Redis cache: cache intent results to skip LLM on repeated queries
    """
    logger.info("Planner Node: Analyzing query...")

    # Extract latest user message
    last_message = state["messages"][-1]
    user_query = last_message.content if hasattr(last_message, "content") else last_message["content"]

    # --- Multi-step execution: load next step without LLM call ---
    current_step_index = state.get("current_step_index", -1)
    plan_steps = state.get("plan_steps", [])

    if current_step_index >= 0 and current_step_index < len(plan_steps):
        step = plan_steps[current_step_index]
        action = step.get("action", "retrieve")
        # Map "respond" to "direct_answer" for graph routing
        if action == "respond":
            action = "direct_answer"

        logger.info(f"Executing plan step {current_step_index + 1}/{len(plan_steps)}: {action}")

        return {
            "current_query": step.get("query", user_query),
            "action": action,
            "tool_name": step.get("tool_name", ""),
            "tool_input": step.get("tool_input", ""),
            "plan": [f"Step {current_step_index + 1}/{len(plan_steps)}"],
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    # --- Fast-path intent classification (skip LLM for obvious cases) ---
    tool_result = state.get("tool_result", "")

    if settings.PLANNER_FAST_CLASSIFY:
        fast_action = _fast_classify(user_query, bool(tool_result))
        if fast_action:
            logger.info(f"Fast-classified intent: {fast_action} (skipped LLM)")
            return {
                "current_query": user_query,
                "plan": ["fast-classified"],
                "action": fast_action,
                "tool_name": "",
                "tool_input": "",
                "current_step_index": -1,
                "iteration_count": state.get("iteration_count", 0) + 1,
            }

    # --- Redis intent cache (skip LLM for repeated queries) ---
    cache_key = None
    if settings.PLANNER_CACHE_ENABLED and not tool_result:
        cache_key = f"planner:{hashlib.sha256(user_query.encode()).hexdigest()[:16]}"
        try:
            cached = await redis_client.get(cache_key, tenant_id="global")
            if cached:
                plan = json_lib.loads(cached)
                logger.info(f"Planner cache hit: action={plan.get('action')}")
                return {
                    "current_query": plan.get("refined_query", user_query),
                    "plan": [plan.get("reasoning", "cached")],
                    "action": plan.get("action", "retrieve"),
                    "tool_name": "",
                    "tool_input": "",
                    "current_step_index": -1,
                    "iteration_count": state.get("iteration_count", 0) + 1,
                }
        except Exception as e:
            logger.debug(f"Planner cache lookup failed: {e}")

    # --- Initial planning: call LLM ---

    # Build context: include tool result if present (ReAct re-planning)
    user_context = user_query
    if tool_result:
        user_context = (
            f"Original query: {user_query}\n\n"
            f"Tool Result from previous step:\n{tool_result}"
        )

    # Format system prompt with available tools
    system_prompt = SYSTEM_PROMPT.format(
        tool_descriptions=get_tool_descriptions()
    )

    # Inject long-term user memories into the prompt
    user_memories = state.get("user_memories", [])
    if user_memories:
        system_prompt += (
            "\n\nUser context from previous sessions:\n"
            + "\n".join(user_memories)
        )

    try:
        response_text = await llm_client.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_context},
            ],
            temperature=0.0,
        )

        plan = extract_json(response_text)
        action = plan.get("action", "retrieve")

        logger.info(f"Plan derived: action={action}, reasoning={plan.get('reasoning', '')}")

        # --- Multi-step plan ---
        if action == "multi_step":
            steps = plan.get("steps", [])
            if not steps:
                # Fallback to single-step retrieve if no steps provided
                action = "retrieve"
            else:
                first_step = steps[0]
                first_action = first_step.get("action", "retrieve")
                if first_action == "respond":
                    first_action = "direct_answer"

                logger.info(f"Multi-step plan with {len(steps)} steps")

                return {
                    "plan_steps": steps,
                    "current_step_index": 0,
                    "step_results": [],
                    "current_query": first_step.get("query", user_query),
                    "action": first_action,
                    "tool_name": first_step.get("tool_name", ""),
                    "tool_input": first_step.get("tool_input", ""),
                    "plan": [plan.get("reasoning", "")],
                    "iteration_count": state.get("iteration_count", 0) + 1,
                }

        # --- Single-step plan ---
        # Cache simple actions in Redis for future reuse
        if cache_key and action in ("retrieve", "direct_answer"):
            try:
                await redis_client.set(
                    cache_key,
                    json_lib.dumps({
                        "action": action,
                        "refined_query": plan.get("refined_query", user_query),
                        "reasoning": plan.get("reasoning", ""),
                    }),
                    tenant_id="global",
                    ex=settings.PLANNER_CACHE_TTL,
                )
            except Exception as e:
                logger.debug(f"Planner cache write failed: {e}")

        return {
            "current_query": plan.get("refined_query", user_query),
            "plan": [plan.get("reasoning", "")],
            "action": action,
            "tool_name": plan.get("tool_name", ""),
            "tool_input": plan.get("tool_input", ""),
            "current_step_index": -1,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    except Exception as e:
        logger.error(f"Planning failed: {e}")
        return {
            "current_query": user_query,
            "plan": ["Error in planning, defaulting to retrieval."],
            "action": "retrieve",
            "tool_name": "",
            "tool_input": "",
            "current_step_index": -1,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }


async def step_advance_node(state: AgentState) -> dict:
    """
    Advance multi-step plan to the next step.
    Collects the result from the just-completed step and increments the index.
    """
    current_index = state.get("current_step_index", 0)
    step_results = list(state.get("step_results", []))

    # Collect the result from the completed step
    latest_result = ""
    if state.get("tool_result"):
        latest_result = state["tool_result"]
    elif state.get("documents"):
        latest_result = "\n".join(state["documents"])
    elif state.get("messages"):
        last_msg = state["messages"][-1]
        latest_result = last_msg.get("content", "") if isinstance(last_msg, dict) else ""

    step_results.append(latest_result)

    logger.info(f"Step advance: completed step {current_index + 1}, moving to {current_index + 2}")

    return {
        "current_step_index": current_index + 1,
        "step_results": step_results,
        "tool_result": "",  # Clear for next step
    }
