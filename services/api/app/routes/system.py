# services/api/app/routes/system.py
"""
System information endpoint — exposes environment, model, and data-source
configuration to the Chat UI.  No secrets are returned.

Also hosts the lightweight client-events sink (`POST /events`). The frontend
analytics layer batches `track()` calls and flushes them via sendBeacon to
this endpoint. We currently just log them — when a real analytics provider
(PostHog / Segment / etc.) is wired up this becomes the relay point.
"""
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter()
logger = logging.getLogger("client-events")


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


# ── Client analytics events ───────────────────────────────────────────


class ClientEvent(BaseModel):
    """One frontend event. Permissive shape — schema is owned by the client."""
    name: str = Field(..., max_length=80)
    ts: int | None = None
    props: dict[str, Any] = Field(default_factory=dict)


class ClientEventBatch(BaseModel):
    events: list[ClientEvent] = Field(default_factory=list, max_length=100)


@router.post("/events")
async def ingest_client_events(batch: ClientEventBatch) -> dict[str, Any]:
    """
    Sink for the frontend's `track()` analytics. The client batches events
    and flushes them via sendBeacon — we accept the batch and just log it
    for now. When a real analytics provider (PostHog / Segment / Snowplow)
    is wired in, this becomes the relay point.

    No auth required: events are anonymous in nature; richer attribution
    happens at the route level via audit_log.
    """
    if batch.events:
        # One log line per event keeps the existing log-aggregation pattern
        # ingestion-friendly (Azure Log Analytics, Datadog Logs, etc.).
        for e in batch.events:
            logger.info("event=%s ts=%s props=%s", e.name, e.ts, e.props)
    return {"received": len(batch.events)}
