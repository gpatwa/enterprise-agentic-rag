# services/data-plane/app/routes/health.py
"""
Data plane health endpoints.

Provides standard K8s probes plus a /health/info endpoint
returning data plane metadata for the control plane.
"""
import time

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()

# Late-initialised client references for readiness checks
_vectordb_client = None
_graphdb_client = None
_start_time = time.time()

# Data plane metadata (set during startup)
_dp_id = "unknown"
_dp_version = "0.0.0"


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus scrape endpoint for process/runtime metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def set_health_clients(vectordb, graphdb):
    """Called during app startup to inject clients for health checks."""
    global _vectordb_client, _graphdb_client
    _vectordb_client = vectordb
    _graphdb_client = graphdb


def set_health_metadata(dp_id: str, version: str):
    """Called during app startup to set data plane identity."""
    global _dp_id, _dp_version
    _dp_id = dp_id
    _dp_version = version


@router.get("/liveness")
async def liveness():
    """Kubernetes liveness probe — process is alive."""
    return {"status": "ok"}


@router.get("/readiness")
async def readiness():
    """Kubernetes readiness probe — all dependencies connected."""
    checks = {}

    # Check VectorDB
    try:
        if _vectordb_client and hasattr(_vectordb_client, "client") and _vectordb_client.client:
            checks["vectordb"] = "ok"
        else:
            checks["vectordb"] = "not_connected"
    except Exception:
        checks["vectordb"] = "error"

    # Check GraphDB
    try:
        if _graphdb_client and _graphdb_client.is_connected:
            checks["graphdb"] = "ok"
        else:
            checks["graphdb"] = "not_connected"
    except Exception:
        checks["graphdb"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
        status_code=status_code,
    )


@router.get("/info")
async def info():
    """
    Data plane metadata endpoint.

    Used by the control plane during registration and health monitoring.
    """
    return {
        "data_plane_id": _dp_id,
        "version": _dp_version,
        "uptime_seconds": int(time.time() - _start_time),
        "status": "healthy",
    }
