# services/api/app/routes/health.py
from fastapi import APIRouter, Response, status

from app.cache.redis import redis_client

router = APIRouter()

# Late-initialised — set by main.py lifespan
_graphdb_client = None
_vectordb_client = None


def set_clients(vectordb, graphdb):
    """Called once during app startup to inject abstracted clients."""
    global _graphdb_client, _vectordb_client
    _graphdb_client = graphdb
    _vectordb_client = vectordb


@router.get("/liveness")
async def liveness():
    """
    K8s Liveness Probe.
    Returns 200 if the server process is running.
    """
    return {"status": "ok"}


@router.get("/readiness")
async def readiness(response: Response):
    """
    K8s Readiness Probe.
    Checks connections to critical dependencies (Postgres, Redis, VectorDB, GraphDB).
    If this fails, K8s stops sending traffic to this pod.
    """
    status_report = {
        "postgres": "down",
        "redis": "down",
        "vectordb": "down",
        "graphdb": "down",
    }
    is_healthy = True

    # 1. Postgres
    try:
        from sqlalchemy import text

        import app.memory.postgres as _pg

        if _pg.AsyncSessionLocal is not None:
            async with _pg.AsyncSessionLocal() as s:
                await s.execute(text("SELECT 1"))
            status_report["postgres"] = "up"
        else:
            is_healthy = False
    except Exception:
        is_healthy = False

    # 2. Redis
    try:
        r = redis_client.get_client()
        if await r.ping():
            status_report["redis"] = "up"
    except Exception:
        is_healthy = False

    # 3. VectorDB (connectivity)
    try:
        if _vectordb_client and _vectordb_client.client:
            status_report["vectordb"] = "up"
        else:
            is_healthy = False
    except Exception:
        is_healthy = False

    # 4. GraphDB (connectivity)
    try:
        if _graphdb_client and hasattr(_graphdb_client, "is_connected"):
            if _graphdb_client.is_connected:
                status_report["graphdb"] = "up"
            else:
                is_healthy = False
        elif _graphdb_client:
            # NullGraphClient is always "up"
            status_report["graphdb"] = "up"
        else:
            is_healthy = False
    except Exception:
        is_healthy = False

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return status_report


@router.get("/deep")
async def deep_health(response: Response):
    """
    Operator-facing deep health check. Probes every dependency with bounded
    timeout and returns per-dependency status + latency.
    """
    import asyncio
    import time

    async def timed(fn, label):
        t0 = time.perf_counter()
        try:
            await asyncio.wait_for(fn(), timeout=3.0)
            return label, "up", int((time.perf_counter() - t0) * 1000)
        except asyncio.TimeoutError:
            return label, "timeout", 3000
        except Exception:
            return label, "error", int((time.perf_counter() - t0) * 1000)

    async def pg():
        from sqlalchemy import text

        import app.memory.postgres as _pg
        if _pg.AsyncSessionLocal is None:
            raise RuntimeError("not initialised")
        async with _pg.AsyncSessionLocal() as s:
            await s.execute(text("SELECT 1"))

    async def redis():
        r = redis_client.get_client()
        await r.ping()

    async def vec():
        if not (_vectordb_client and _vectordb_client.client):
            raise RuntimeError("not initialised")

    async def graph():
        if not _graphdb_client:
            raise RuntimeError("not initialised")
        if hasattr(_graphdb_client, "is_connected") and not _graphdb_client.is_connected:
            raise RuntimeError("not connected")

    results = await asyncio.gather(
        timed(pg, "postgres"),
        timed(redis, "redis"),
        timed(vec, "vectordb"),
        timed(graph, "graphdb"),
    )
    body = {label: {"status": s, "latency_ms": ms} for label, s, ms in results}
    if any(v["status"] != "up" for v in body.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return body
