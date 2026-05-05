# services/api/app/agents/nodes/evaluator.py
import logging

from app.agents.json_utils import extract_json
from app.agents.state import AgentState
from app.clients.ray_llm import llm_client

logger = logging.getLogger(__name__)

EVAL_PROMPT = """You are a Response Quality Evaluator.
Evaluate whether the answer adequately addresses the question using the provided context.

Question: {question}

Context provided:
{context}

Answer given:
{answer}

Score the answer from 1-5:
1 = Completely wrong or irrelevant
2 = Partially relevant but misses key points
3 = Acceptable but could be more complete
4 = Good answer, well-grounded in context
5 = Excellent, comprehensive, well-cited

Output JSON ONLY:
{{
    "score": <1-5>,
    "reasoning": "Brief explanation",
    "refined_query": "A better search query if score <= 2, empty string otherwise"
}}"""


async def evaluator_node(state: AgentState) -> dict:
    """Evaluate response quality. Decide accept or retry."""
    retry_count = state.get("retry_count", 0)

    # Skip evaluation if we already retried once
    if retry_count >= 1:
        logger.info("Evaluator: Max retries reached, accepting answer.")
        return {"eval_score": 0, "eval_reasoning": "Skipped (max retries)"}

    # Extract the answer from the last assistant message
    messages = state.get("messages", [])
    answer = ""
    for msg in reversed(messages):
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        if content and not content.startswith("[Tool"):
            answer = content
            break

    if not answer:
        return {"eval_score": 5, "eval_reasoning": "No answer to evaluate"}

    context = "\n".join(state.get("documents", []))
    tool_result = state.get("tool_result", "")
    if tool_result:
        context += f"\n\nTool Result:\n{tool_result}"

    question = state.get("current_query", "")

    try:
        response_text = await llm_client.chat_completion(
            messages=[{
                "role": "user",
                "content": EVAL_PROMPT.format(
                    question=question,
                    context=context[:2000],
                    answer=answer[:1000],
                ),
            }],
            temperature=0.0,
        )
        result = extract_json(response_text)
        score = result.get("score", 5)
        reasoning = result.get("reasoning", "")
        refined_query = result.get("refined_query", "")

        logger.info(f"Evaluator score: {score}/5 — {reasoning}")

        update = {
            "eval_score": score,
            "eval_reasoning": reasoning,
        }

        # If score is low and we have a better query, update it for retry
        if score <= 2 and refined_query:
            update["current_query"] = refined_query

        return update

    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        return {"eval_score": 0, "eval_reasoning": f"Evaluation error: {e}"}


async def retry_node(state: AgentState) -> dict:
    """Prepare state for a retry: increment counter, clear stale data."""
    logger.info("Retry node: Clearing stale data for re-retrieval.")
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "documents": [],
        "tool_result": "",
    }
