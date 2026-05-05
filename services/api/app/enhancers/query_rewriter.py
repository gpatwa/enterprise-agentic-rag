# services/api/app/enhancers/query_rewriter.py
from typing import Dict, List

from app.clients.ray_llm import llm_client

SYSTEM_PROMPT = """
You are a Query Rewriter.
Your task is to rewrite the latest user question to be a standalone search query,
resolving coreferences (he, she, it, they) using the conversation history.

History:
{history}

Latest Question: {question}

Output ONLY the rewritten question. If no rewriting is needed, output the latest question as is.
"""

async def rewrite_query(question: str, history: List[Dict[str, str]]) -> str:
    """
    Uses LLM to de-contextualize the query for better Vector Search.
    """
    if not history:
        return question

    # Format history into a string
    history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])

    prompt = SYSTEM_PROMPT.format(history=history_str, question=question)

    try:
        # Call the internal Ray LLM
        rewritten = await llm_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0 # Strict logic
        )
        return rewritten.strip()
    except Exception:
        # Fallback to original query if LLM fails
        return question
