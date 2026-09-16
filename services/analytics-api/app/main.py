from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import settings
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
    yield
    await analytics_service.close()


app = FastAPI(
    title="Compass Analytics API",
    version="0.1.0",
    lifespan=lifespan,
)

if settings.ENV == "prod" and (
    not settings.cors_origins or settings.cors_origins == ["*"]
):
    raise RuntimeError("ANALYTICS_CORS_ORIGINS must be explicit in production")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
)


async def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.ANALYTICS_API_KEY and x_api_key != settings.ANALYTICS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid analytics API key",
        )


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
        context_bootstrap_error=analytics_service.context_bootstrap.state.error,
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
async def query(request: AnalyticsQueryRequest) -> AnalyticsQueryResponse:
    return await analytics_service.query(request)
