# services/api/app/tools/web_search.py
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def web_search_tool(query: str) -> str:
    """
    Tool: Search the Internet.
    Use this for current events or public info not in the internal DB.
    """
    api_key = settings.TAVILY_API_KEY
    if not api_key:
        logger.warning("Web search disabled — TAVILY_API_KEY not set in config")
        return "Web search is disabled (TAVILY_API_KEY not configured)."

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 3
                },
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            formatted = "\n".join([f"- {r['title']}: {r['content']} ({r['url']})" for r in results])

            return formatted if formatted else "No results found on the web."

    except Exception as e:
        return f"Web Search Error: {str(e)}"
