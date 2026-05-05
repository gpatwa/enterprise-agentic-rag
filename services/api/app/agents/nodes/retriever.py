# services/api/app/agents/nodes/retriever.py
import asyncio
import logging
from typing import Dict

from langchain_core.runnables import RunnableConfig

from app.agents.state import AgentState
from app.clients.ray_embed import embed_client
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"

# ------------------------------------------------------------------
# Late-initialised references — set by main.py lifespan via set_clients()
# ------------------------------------------------------------------
_vectordb_client = None
_graphdb_client = None
_reranker_client = None
_storage_client = None
_gemini_embed_client = None


def set_clients(vectordb, graphdb, reranker=None, storage=None, gemini_embed=None):
    """Called once during app startup to inject abstracted clients."""
    global _vectordb_client, _graphdb_client, _reranker_client, _storage_client, _gemini_embed_client
    _vectordb_client = vectordb
    _graphdb_client = graphdb
    _reranker_client = reranker
    _storage_client = storage
    _gemini_embed_client = gemini_embed


async def retrieve_node(state: AgentState, config: RunnableConfig) -> Dict:
    """
    Executes Hybrid Retrieval with optional Re-ranking:
    1. Embeds the user query.
    2. Runs Vector Search AND Graph Search concurrently.
    3. Merges and deduplicates results.
    4. Re-ranks merged results (if reranker is configured).

    When MULTIMODAL_ENABLED, also searches the multimodal Qdrant collection
    using Gemini embeddings for cross-modal retrieval (text query → image results).

    Both searches are filtered by tenant_id from the LangGraph config
    to enforce cross-tenant data isolation.
    """
    query = state["current_query"]

    # Extract tenant_id from LangGraph configurable (set in chat.py)
    configurable = config.get("configurable", {})
    tenant_id = configurable.get("tenant_id", DEFAULT_TENANT_ID)

    logger.info(f"Retrieving context for: {query} (tenant={tenant_id})")

    # Step 1: Reuse pre-computed embedding from cache check, or compute fresh
    query_vector = state.get("query_embedding") or await embed_client.embed_query(query)
    if state.get("query_embedding"):
        logger.info("Reusing pre-computed query embedding from cache check")

    # Step 2: Define the tasks for Parallel Execution

    # Build tenant filter (disabled in single-tenant data plane mode)
    tenant_filter = {} if settings.SINGLE_TENANT_MODE else {"tenant_id": tenant_id}

    # Task A: Vector Search (Semantic Similarity) — filtered by tenant_id
    async def run_vector_search():
        results = await _vectordb_client.search(
            collection=settings.QDRANT_COLLECTION,
            vector=query_vector,
            limit=15,
            filters=tenant_filter,
        )
        # Deduplicate by text content
        seen_texts = set()
        unique_docs = []
        for r in results:
            text = r['payload']['text']
            if text not in seen_texts:
                seen_texts.add(text)
                filename = r['payload'].get('filename',
                    r['payload'].get('metadata', {}).get('filename', 'unknown'))
                unique_docs.append(f"{text} [Source: {filename}]")
            if len(unique_docs) >= 8:
                break
        return unique_docs

    # Task B: Graph Search (Structural Relationships) — filtered by tenant_id
    graph_tenant = None if settings.SINGLE_TENANT_MODE else tenant_id
    async def run_graph_search():
        try:
            return await _graphdb_client.query_related(
                query=query, tenant_id=graph_tenant, limit=5
            )
        except Exception as e:
            logger.error(f"Graph search failed: {e}")
            return []

    # Task C: Multimodal Search (cross-modal: text query → image results)
    async def run_multimodal_search():
        if not settings.MULTIMODAL_ENABLED or not _gemini_embed_client:
            return []
        try:
            # Embed query with Gemini for the multimodal collection
            mm_query_vector = await _gemini_embed_client.embed_query(query)
            results = await _vectordb_client.search(
                collection=settings.MULTIMODAL_COLLECTION,
                vector=mm_query_vector,
                limit=10,
                filters=tenant_filter,
            )
            docs = []
            for r in results:
                content_type = r['payload'].get('content_type', 'text')
                filename = r['payload'].get('filename', 'unknown')

                if content_type == "image":
                    image_key = r['payload'].get('image_key', '')
                    image_url = ""
                    if image_key and _storage_client:
                        image_url = _storage_client.generate_presigned_download_url(
                            image_key, expires_in=3600
                        )
                    docs.append({
                        "type": "image",
                        "url": image_url,
                        "caption": r['payload'].get('text', ''),
                        "filename": filename,
                        "mime_type": r['payload'].get('image_mime_type', 'image/png'),
                        "score": r.get('score', 0),
                    })
                else:
                    text = r['payload']['text']
                    docs.append(f"{text} [Source: {filename}]")

                if len(docs) >= 5:
                    break
            return docs
        except Exception as e:
            logger.error(f"Multimodal search failed: {e}")
            return []

    # Step 3: Run all searches in parallel
    vector_docs, graph_docs, mm_docs = await asyncio.gather(
        run_vector_search(), run_graph_search(), run_multimodal_search()
    )

    # Step 4: Merge (graph docs first for priority, then vector, then multimodal)
    combined_docs = graph_docs + [d for d in vector_docs if d not in graph_docs]

    # Add multimodal results (images go at the end, text deduped)
    for d in mm_docs:
        if isinstance(d, dict):
            # Image doc — always include
            combined_docs.append(d)
        elif d not in combined_docs:
            combined_docs.append(d)

    logger.info(
        f"Retrieved {len(combined_docs)} docs "
        f"(vector={len(vector_docs)}, graph={len(graph_docs)}, "
        f"multimodal={len(mm_docs)}, tenant={tenant_id})"
    )

    # Step 5: Re-rank merged results (if reranker is configured)
    # Only re-rank text documents; image docs pass through
    if _reranker_client and combined_docs:
        try:
            text_docs = [d for d in combined_docs if isinstance(d, str)]
            image_docs = [d for d in combined_docs if isinstance(d, dict)]

            if text_docs:
                scored_docs = await _reranker_client.rerank(
                    query=query, documents=text_docs, top_k=8
                )
                reranked_text = [sd.text for sd in scored_docs]
                logger.info(
                    f"Re-ranked {len(text_docs)} → {len(reranked_text)} docs "
                    f"(top score: {scored_docs[0].score:.2f})"
                )
                combined_docs = reranked_text + image_docs
        except Exception as e:
            logger.warning(f"Re-ranking failed ({e}), using original order")

    if combined_docs:
        first = combined_docs[0]
        preview = first[:120] if isinstance(first, str) else f"[image: {first.get('filename', '')}]"
        logger.info(f"First doc preview: {preview}...")
    else:
        logger.warning(f"No documents found for query: '{query}'")

    # Update State
    return {"documents": combined_docs}
