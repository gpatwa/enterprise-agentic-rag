"""Analytics runtime contracts for bounded execution and operational telemetry."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QueryBudget(BaseModel):
    timeout_seconds: float = Field(default=30, gt=0, le=600)
    max_rows: int = Field(default=10_000, ge=1, le=1_000_000)
    max_concurrency: int = Field(default=4, ge=1, le=1_000)
    max_cost_units: float = Field(default=100, gt=0)


class RuntimeQueryRequest(BaseModel):
    query_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    cancellation_key: str = Field(min_length=1, max_length=255)
    budget: QueryBudget = Field(default_factory=QueryBudget)


class QueryTelemetry(BaseModel):
    query_id: str
    tenant_id: str
    trace_id: str
    stage: Literal["ingress", "planning", "compilation", "execution", "evidence", "completed", "failed"]
    duration_ms: float = Field(ge=0)
    rows: int | None = Field(default=None, ge=0)
    cost_units: float | None = Field(default=None, ge=0)


class UsageRecord(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    query_id: str
    tenant_id: str
    model_units: float = Field(default=0, ge=0)
    warehouse_units: float = Field(default=0, ge=0)
    duration_ms: float = Field(default=0, ge=0)
