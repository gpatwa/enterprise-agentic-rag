# services/api/app/tools/vector_search.py
from app.clients.qdrant import qdrant_client
from app.clients.ray_embed import embed_client


async def search_vector_tool(query: str) -> str:
    """
    Tool: Search the Vector Database for documents.
    Useful when the user asks to 'find documents about X'.
    """
    try:
        # 1. Embed query
        vector = await embed_client.embed_query(query)

        # 2. Search
        results = await qdrant_client.search(vector, limit=3)

        if not results:
            return "No relevant documents found."

        # 3. Format Output
        formatted = ""
        for r in results:
            meta = r.payload.get("metadata", {})
            filename = meta.get("filename", "Unknown")
            page = meta.get("page_number", "N/A")
            formatted += f"- Content: {r.payload.get('text', '')[:200]}... [Source: {filename}, Page: {page}]\n"

        return formatted

    except Exception as e:
        return f"Search Error: {str(e)}"
