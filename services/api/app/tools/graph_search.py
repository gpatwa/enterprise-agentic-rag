# services/api/app/tools/graph_search.py
import json

from app.clients.neo4j import neo4j_client
from app.clients.ray_llm import llm_client

SYSTEM_PROMPT = """
You are a Knowledge Graph Helper.
Extract the core entities from the user's question to perform a search.

Question: {question}

Output JSON only:
{
    "entities": ["list", "of", "names"]
}
"""

async def search_graph_tool(question: str) -> str:
    """
    Safely searches the graph by extracting entities and looking up their neighborhoods.
    Prevents Cypher Injection.
    """
    try:
        # 1. Extract Entities (No Code Generation)
        response_text = await llm_client.chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(question=question)}
            ],
            temperature=0.0,
            json_mode=True
        )
        data = json.loads(response_text)
        entities = data.get("entities", [])

        if not entities:
            return "No specific entities identified to search."

        # 2. Execute Parameterized Query (Safe)
        # We explicitly define the query logic in code, not LLM.
        cypher_query = """
        UNWIND $names AS target_name
        CALL db.index.fulltext.queryNodes("entity_index", target_name) YIELD node, score
        MATCH (node)-[r]-(neighbor)
        RETURN node.name AS source, type(r) AS rel, neighbor.name AS target
        LIMIT 10
        """

        results = await neo4j_client.query(cypher_query, {"names": entities})

        if not results:
            return "No knowledge graph connections found."

        return str(results)

    except Exception as e:
        return f"Graph search error: {str(e)}"
