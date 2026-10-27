from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api_v2 import V2Runtime, build_v2_router
from app.config import settings, v1_enabled
from app.demo import build_demo_router
from app.runtime.shadow import ShadowRuntime, query_with_shadow
from app.service import AnalyticsService
from packages.platform_contracts.analytics import (
    AnalyticsHealthResponse,
    AnalyticsQueryRequest,
    AnalyticsQueryResponse,
    AnalyticsSchemaResponse,
)

analytics_service = AnalyticsService(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await analytics_service.start()
    if settings.ANALYTICS_V2_ENABLED and v2_runtime.service is None:
        from app.runtime.pilot_wiring import build_pilot_runtime

        built = build_pilot_runtime(settings)  # fails the start-up loudly rather than serving 503s
        v2_runtime.service, v2_runtime.verifier, v2_runtime.feedback = built.service, built.verifier, built.feedback
        v2_runtime.resolver, v2_runtime.briefs = built.resolver, built.briefs  # review-assistant routes need the briefs
        v2_runtime.governed = built.governed  # type: ignore[attr-defined]
        if settings.ANALYTICS_DEMO_ENABLED and settings.ANALYTICS_DEMO_TENANT not in built.governed.contexts:
            raise RuntimeError("ANALYTICS_DEMO_ENABLED needs a certified contract for ANALYTICS_DEMO_TENANT")
        if settings.ANALYTICS_DEMO_ENABLED and settings.ANALYTICS_DEMO_TENANT in (settings.entra_tenant_targets()):
            raise RuntimeError("the demo tenant must not be a tenant that signed-in users map to")
    yield
    await analytics_service.close()


app = FastAPI(
    title="Compass Analytics API",
    version="0.1.0",
    lifespan=lifespan,
)

if settings.ENV == "prod" and (not settings.cors_origins or settings.cors_origins == ["*"]):
    raise RuntimeError("ANALYTICS_CORS_ORIGINS must be explicit in production")
if settings.ENV == "prod" and not settings.ANALYTICS_API_KEY:
    raise RuntimeError("ANALYTICS_API_KEY must be set in production")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "X-API-Key",
        "X-Request-ID",
        "Authorization",
        "Idempotency-Key",
        "X-Analytics-Purpose",
        "X-Demo-Visitor",
    ],
)


async def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.ANALYTICS_API_KEY and x_api_key != settings.ANALYTICS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid analytics API key",
        )


v2_runtime = V2Runtime()
shadow_runtime = ShadowRuntime()
app.include_router(build_v2_router(v2_runtime, verify_api_key))
app.include_router(build_demo_router(v2_runtime, verify_api_key, settings))


@app.get("/health", response_model=AnalyticsHealthResponse)
async def health() -> AnalyticsHealthResponse:
    ready = (
        analytics_service.database_configured
        and analytics_service.llm_configured
        and analytics_service.context_index_ready
    )
    return AnalyticsHealthResponse(
        status="ready" if ready else "degraded",
        database_configured=analytics_service.database_configured,
        llm_configured=analytics_service.llm_configured,
        context_index_configured=analytics_service.context_bootstrap.state.configured,
        context_index_ready=analytics_service.context_bootstrap.state.ready,
        context_documents_indexed=analytics_service.context_bootstrap.state.indexed_documents,
        dashboard_configured=analytics_service.context_bootstrap.state.dashboard_configured,
        dashboard_ready=analytics_service.context_bootstrap.state.dashboard_ready,
        # A short code only: raw exception text can carry hosts, paths, or credentials.
        context_bootstrap_error="context_bootstrap_failed" if analytics_service.context_bootstrap.state.error else None,
    )


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus scrape endpoint for process/runtime metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get(
    "/api/v1/analytics/schema",
    response_model=AnalyticsSchemaResponse,
    dependencies=[Depends(verify_api_key)],
)
async def schema(dataset: str = "olist") -> AnalyticsSchemaResponse:
    return analytics_service.schema(dataset)


@app.post(
    "/api/v1/analytics/query",
    response_model=AnalyticsQueryResponse,
    dependencies=[Depends(verify_api_key)],
)
async def query(
    request: AnalyticsQueryRequest,
    authorization: str | None = Header(default=None),
    x_analytics_purpose: str | None = Header(default=None),
) -> AnalyticsQueryResponse:
    if not v1_enabled(settings):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="v1_disabled")
    routed = shadow_runtime.decide(authorization, x_analytics_purpose)
    if routed is None:
        return await analytics_service.query(request)
    decision, identity = routed
    return await query_with_shadow(
        lambda: analytics_service.query(request),
        decision=decision,
        identity=identity,
        purpose=x_analytics_purpose,
        request_text=request.query,
        analyzer=shadow_runtime.analyzer,
        sink=shadow_runtime.sink,
        timeout_seconds=shadow_runtime.timeout_seconds,
    )
