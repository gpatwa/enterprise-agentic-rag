# services/api/app/agents/state.py
import operator
from typing import Annotated, List, TypedDict, Union


class AgentState(TypedDict):
    """
    The state object passed between nodes in the LangGraph.
    Tracks the conversation history and current step data.
    """
    # Using 'operator.add' means new messages are appended, not overwritten
    messages: Annotated[List[dict], operator.add]

    # Context retrieved from RAG (Vector + Graph)
    # Items are either plain strings (text) or dicts with type/content/url keys (multimodal)
    documents: List[Union[str, dict]]

    # The current question being processed
    current_query: str

    # Internal scratchpad for the planner
    plan: List[str]

    # Routing — set by planner, read by conditional edges
    action: str  # "retrieve" | "direct_answer" | "tool_use"

    # Tool execution — set by planner, consumed by tool_node
    tool_name: str   # e.g. "calculator", "web_search"
    tool_input: str  # parameter value for the selected tool
    tool_result: str  # output from tool execution

    # ReAct loop guard — prevents infinite tool loops
    iteration_count: int

    # Multi-step planning — decompose complex queries into sub-steps
    plan_steps: List[dict]    # [{"action", "query", "tool_name", "tool_input"}]
    current_step_index: int   # -1 = single-step mode, 0+ = executing step N
    step_results: List[str]   # accumulated results from completed steps

    # Self-evaluation — LLM scores answer quality, retry once if poor
    eval_score: int           # 0 = not evaluated, 1-5 = quality score
    eval_reasoning: str       # evaluator's explanation
    retry_count: int          # max 1 retry

    # Long-term memory — user preferences/facts from previous sessions
    user_memories: List[str]  # loaded at session start

    # Pre-computed query embedding from semantic cache check (avoids duplicate embed call)
    query_embedding: List[float]

    # Assembled context from context layers (business rules, glossary, metadata)
    context_layers: str

    # Data analytics — SQL query results
    data_query_sql: str           # Generated SQL for transparency
    data_query_result: str        # JSON-serialized {columns, rows, row_count}
    data_query_error: str         # Error message if query fails
    data_query_time_ms: int       # Execution time in milliseconds
