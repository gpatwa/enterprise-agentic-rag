# services/api/app/routes/system.py
"""
System information endpoint — exposes environment, model, and data-source
configuration to the Chat UI.  No secrets are returned.
"""
from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/info")
async def system_info():
    """
    Return non-sensitive system configuration for the Chat UI status bar.
    """
    # Resolve active model names based on provider
    llm_model = (
        settings.OPENAI_MODEL
        if settings.LLM_PROVIDER == "openai"
        else settings.LLM_MODEL
    )
    embed_model = (
        settings.OPENAI_EMBED_MODEL
        if settings.EMBED_PROVIDER == "openai"
        else settings.EMBED_MODEL
    )

    return {
        "environment": {
            "env": settings.ENV,
            "deployment_mode": settings.DEPLOYMENT_MODE,
            "cloud_provider": settings.CLOUD_PROVIDER,
        },
        "models": {
            "llm_provider": settings.LLM_PROVIDER,
            "llm_model": llm_model,
            "embed_provider": settings.EMBED_PROVIDER,
            "embed_model": embed_model,
            "reranker": settings.RERANKER_PROVIDER,
        },
        "data_sources": {
            "vectordb": settings.VECTORDB_PROVIDER,
            "graphdb": settings.GRAPHDB_PROVIDER,
            "storage": settings.STORAGE_PROVIDER,
        },
        "optimizations": {
            "semantic_cache_threshold": settings.SEMANTIC_CACHE_THRESHOLD,
            "evaluator_skip_with_context": settings.EVALUATOR_SKIP_WITH_CONTEXT,
            "planner_fast_classify": settings.PLANNER_FAST_CLASSIFY,
            "planner_cache": settings.PLANNER_CACHE_ENABLED,
            "stream_response": settings.LLM_STREAM_RESPONSE,
        },
    }
