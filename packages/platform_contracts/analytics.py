"""Public API contracts for the analytics product.

These models are intentionally free of analytics implementation details. The
analytics API owns SQL generation and execution; clients depend only on this
versioned request/response surface.
"""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalyticsQueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2_000)
    tenant_id: str = Field(default="local-demo", min_length=1, max_length=255)
    user_id: str = Field(default="local-user", min_length=1, max_length=255)
    dataset: str = Field(default="olist", min_length=1, max_length=100)


class AnalyticsQueryResponse(BaseModel):
    contract_version: Literal["v1"] = "v1"
    query_id: str
    query: str
    dataset: str
    status: Literal["succeeded", "failed"]
    sql: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: int = 0
    truncated: bool = False
    chart_spec: dict[str, Any] | None = None
    error: str = ""
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AnalyticsSchemaResponse(BaseModel):
    contract_version: Literal["v1"] = "v1"
    dataset: str
    tables: list[str]
    metrics: list[str]


class AnalyticsHealthResponse(BaseModel):
    service: Literal["analytics-api"] = "analytics-api"
    status: Literal["ready", "degraded"]
    database_configured: bool
    llm_configured: bool
    context_index_configured: bool = False
    context_index_ready: bool = False
    context_documents_indexed: int = 0
    dashboard_configured: bool = False
    dashboard_ready: bool = False
    context_bootstrap_error: str | None = None
    contract_version: Literal["v1"] = "v1"
