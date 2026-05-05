# services/api/app/agents/nodes/clarify.py
"""
Iterative clarification node.

Detects when a query is too ambiguous to answer well, and emits a
clarifying question instead of running the full pipeline. A user-flagged
clarification cuts hallucination risk on high-stakes asks (revenue,
churn, "active users", etc.) where ambiguity = wrong answer.

Wired conditionally: enabled via settings.CLARIFICATION_ENABLED. When
enabled, the planner routes to this node when its confidence is low.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.state import AgentState
from app.config import settings

logger = logging.getLogger(__name__)


_CLARIFY_PROMPT = """You are a precision-first analyst. Given a user query, decide if it's ambiguous enough that answering it directly risks giving a wrong answer.

A query is AMBIGUOUS if any of:
- It references a metric without a clear definition (e.g. "revenue" when company has multiple revenue defs)
- It references a time window without bounds ("recently", "lately")
- It uses pronouns or references with unclear antecedents
- It conflates two distinct entities (e.g. "customer" vs "account")

Output ONLY valid JSON, nothing else:
{{"needs_clarification": true|false, "question": "specific clarifying question OR empty string", "guess": "best-guess interpretation OR empty string"}}

User query: {q}"""


async def clarify_node(state: AgentState, config=None) -> dict[str, Any]:
    """
    Decides whether to clarify. Returns:
      - needs_clarification (bool)
      - clarification_question (str): the question to ask the user
      - clarification_guess (str): the assumed interpretation if user proceeds anyway

    The state machine (graph.py) routes to "responder" with a clarification
    payload when needs_clarification=True; otherwise control falls through
    to the normal retrieval path.
    """
    if not getattr(settings, "CLARIFICATION_ENABLED", False):
        return {
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_guess": "",
        }

    query = state.get("current_query", "") or ""
    if not query.strip():
        return {
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_guess": "",
        }

    # Get LLM client from config (graph passes it through)
    llm = None
    if config:
        llm = config.get("configurable", {}).get("llm")
    if llm is None:
        # Without an LLM we can't reason about ambiguity; let the request through.
        return {
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_guess": "",
        }

    try:
        response = await llm.chat_completion(
            messages=[{"role": "user", "content": _CLARIFY_PROMPT.format(q=query)}],
            temperature=0.0,
        )
        # Tolerate bare JSON or fenced/prefixed JSON
        text = (response or "").strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        parsed = json.loads(text)
        return {
            "needs_clarification": bool(parsed.get("needs_clarification", False)),
            "clarification_question": str(parsed.get("question", ""))[:300],
            "clarification_guess": str(parsed.get("guess", ""))[:300],
        }
    except Exception as e:
        logger.warning("clarify_node: failed to classify, allowing through: %s", e)
        return {
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_guess": "",
        }
