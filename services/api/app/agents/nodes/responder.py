# services/api/app/agents/nodes/responder.py
import logging

from app.agents.state import AgentState
from app.clients.ray_llm import llm_client
from app.tools.web_search import web_search_tool

logger = logging.getLogger(__name__)


async def generate_node(state: AgentState) -> dict:
    """
    Synthesizes the final answer using retrieved documents.
    Supports multimodal context: when image documents are present,
    formats them as vision-compatible message parts for the LLM.
    Falls back to web search when no internal documents are found.
    """
    query = state["current_query"]
    documents = state.get("documents", [])
    tool_result = state.get("tool_result", "")

    # Separate text and image documents
    text_docs = []
    image_docs = []
    for d in documents:
        if isinstance(d, dict) and d.get("type") == "image":
            image_docs.append(d)
        elif isinstance(d, dict) and d.get("content"):
            text_docs.append(d["content"])
        elif isinstance(d, str):
            text_docs.append(d)

    # Construct Context String from text documents
    context_str = "\n\n".join(text_docs)
    if tool_result:
        context_str += f"\n\nTool Result:\n{tool_result}"

    # Include accumulated results from multi-step planning
    step_results = state.get("step_results", [])
    if step_results:
        context_str += "\n\nPrevious Step Results:\n" + "\n---\n".join(step_results)

    # Include context layers (business rules, glossary, metadata)
    context_layers = state.get("context_layers", "")
    if context_layers:
        context_str += f"\n\n--- Business Context ---\n{context_layers}"

    # Include data analytics results
    data_error = state.get("data_query_error", "")
    if data_error:
        context_str += f"\n\n--- Data Query Error ---\n{data_error}\nPlease inform the user about the error and suggest a refined question."

    # Include long-term user memories
    user_memories = state.get("user_memories", [])
    if user_memories:
        context_str += "\n\nUser Preferences/Facts:\n" + "\n".join(user_memories)

    # Fallback: if no context from retrieval or tools, try web search
    if not context_str.strip() and not image_docs:
        logger.info(f"No internal documents found for '{query}', trying web search...")
        try:
            web_result = await web_search_tool(query)
            if web_result and "disabled" not in web_result.lower() and "error" not in web_result.lower():
                context_str = f"Web Search Results:\n{web_result}"
                logger.info("Web search returned results as fallback")
            else:
                logger.info(f"Web search unavailable: {web_result}")
        except Exception as e:
            logger.warning(f"Web search fallback failed: {e}")

    logger.info(
        f"Responder context length: {len(context_str)} chars, "
        f"text docs: {len(text_docs)}, image docs: {len(image_docs)}"
    )

    instructions = """You are a helpful Enterprise Assistant. Use the context below to answer the user's question.

Instructions:
1. If context contains relevant information, answer using it and cite sources with [Source: filename].
2. If context is from web search results, answer using it and mention the source URLs.
3. If images are provided as context, describe what you see and incorporate relevant details into your answer.
4. If no context is available, provide a helpful answer from your general knowledge and note that no internal documents were found.
5. Be concise and professional.
6. If data query results are provided, synthesize a clear natural language answer from the data. Highlight key numbers, trends, and insights. Be specific with values. Do not just repeat the table — interpret it."""

    # Build messages — use vision format when images are present
    if image_docs:
        # Vision-capable LLM format: content is a list of text + image_url parts
        content_parts = [
            {"type": "text", "text": f"{instructions}\n\nContext:\n{context_str}\n\nQuestion:\n{query}"}
        ]
        for img in image_docs:
            if img.get("url"):
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": img["url"]}
                })
                if img.get("caption"):
                    content_parts.append({
                        "type": "text",
                        "text": f"[Image from {img.get('filename', 'unknown')}: {img['caption']}]"
                    })

        messages = [{"role": "user", "content": content_parts}]
    else:
        # Standard text-only prompt
        prompt = f"""{instructions}

Context:
{context_str}

Question:
{query}"""
        messages = [{"role": "user", "content": prompt}]

    # Call LLM
    answer = await llm_client.chat_completion(
        messages=messages,
        temperature=0.3
    )

    # Return dictionary to update state (add the AI message)
    return {
        "messages": [{"role": "assistant", "content": answer}]
    }
