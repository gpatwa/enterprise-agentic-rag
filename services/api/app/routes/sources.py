# services/api/app/routes/sources.py
"""
Sources health endpoint — live probes against connected datastores.

Probes are run in parallel with short timeouts. If any probe fails, the
source is marked "stale" (recoverable error) or "error" (permanent), so
the right-rail keeps rendering instead of hard-failing.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.auth.tenant import TenantContext, get_tenant_context

router = APIRouter()
logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 3.0


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


async def _probe_postgres() -> dict[str, Any]:
    """Counts rows in the chat_history table as a liveness signal."""
    try:
        import app.memory.postgres as _pg
        from sqlalchemy import text

        if _pg.AsyncSessionLocal is None:
            return {"type": "postgres", "name": "PostgreSQL", "status": "not_connected"}

        async with _pg.AsyncSessionLocal() as s:
            # Use a cheap query — pg_stat-derived row estimate would be even cheaper
            # but works less universally. COUNT(*) is fine for a few-million-row table.
            row_count = await s.scalar(text("SELECT COUNT(*) FROM chat_history"))
        return {
            "type": "postgres",
            "name": "PostgreSQL",
            "row_count": int(row_count or 0),
            "last_synced_at": _now_iso(),
            "status": "fresh",
        }
    except Exception as e:
        logger.warning("postgres probe failed: %s", e)
        return {"type": "postgres", "name": "PostgreSQL", "status": "error"}


async def _probe_qdrant() -> dict[str, Any]:
    try:
        from app.config import settings

        if settings.VECTORDB_PROVIDER != "qdrant":
            return {"type": "qdrant", "name": "Qdrant Vector", "status": "not_connected"}

        from qdrant_client import AsyncQdrantClient

        client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        try:
            info = await client.get_collection(settings.QDRANT_COLLECTION)
            return {
                "type": "qdrant",
                "name": "Qdrant Vector",
                "chunk_count": info.points_count or 0,
                "last_synced_at": _now_iso(),
                "status": "fresh",
            }
        finally:
            await client.close()
    except Exception as e:
        logger.warning("qdrant probe failed: %s", e)
        return {"type": "qdrant", "name": "Qdrant Vector", "status": "error"}


async def _probe_neo4j() -> dict[str, Any]:
    try:
        from app.config import settings

        if settings.GRAPHDB_PROVIDER != "neo4j":
            return {"type": "neo4j", "name": "Neo4j Graph", "status": "not_connected"}

        from neo4j import AsyncGraphDatabase

        driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD or ""),
        )
        try:
            async with driver.session() as session:
                result = await session.run("MATCH (n) RETURN count(n) AS c")
                rec = await result.single()
                count = rec["c"] if rec else 0
            return {
                "type": "neo4j",
                "name": "Neo4j Graph",
                "node_count": int(count),
                "last_synced_at": _now_iso(),
                "status": "fresh",
            }
        finally:
            await driver.close()
    except Exception as e:
        logger.warning("neo4j probe failed: %s", e)
        return {"type": "neo4j", "name": "Neo4j Graph", "status": "error"}


async def _with_timeout(coro, timeout: float, fallback: dict) -> dict:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return {**fallback, "status": "stale"}
    except Exception:
        return {**fallback, "status": "error"}


@router.get("/health")
async def sources_health(_: TenantContext = Depends(get_tenant_context)):
    """
    Live health for the right-rail Sources panel. Tenant-aware — but the
    underlying datastores are shared, so we don't filter by tenant_id here.
    Per-tenant row counts come from individual feature endpoints.
    """
    pg, qd, neo = await asyncio.gather(
        _with_timeout(
            _probe_postgres(), PROBE_TIMEOUT_SECONDS, {"type": "postgres", "name": "PostgreSQL"}
        ),
        _with_timeout(
            _probe_qdrant(), PROBE_TIMEOUT_SECONDS, {"type": "qdrant", "name": "Qdrant Vector"}
        ),
        _with_timeout(
            _probe_neo4j(), PROBE_TIMEOUT_SECONDS, {"type": "neo4j", "name": "Neo4j Graph"}
        ),
    )

    return {
        "sources": [
            pg,
            qd,
            neo,
            {"type": "slack", "name": "Slack export", "status": "not_connected"},
        ],
        "probed_at": _now_iso(),
    }
