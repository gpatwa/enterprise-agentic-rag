"""Versioning, rollout, drift, and validated correction contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class ComponentVersion(BaseModel):
    component: Literal["prompt", "model", "semantic_contract", "policy"]
    version: str = Field(min_length=1, max_length=255)
    immutable_digest: str = Field(min_length=1, max_length=255)
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RolloutState(BaseModel):
    component: str
    active_version: str
    canary_version: str | None = None
    canary_percent: int = Field(default=0, ge=0, le=100)
    rollback_version: str | None = None


class DriftSignal(BaseModel):
    signal_type: Literal["retrieval", "clarification", "execution_error", "semantic_freshness", "quality"]
    tenant_id: str
    value: float = Field(ge=0)
    threshold: float = Field(ge=0)
    alert: bool
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ValidatedCorrection(BaseModel):
    correction_id: str
    tenant_id: str
    scope: Literal["tenant", "contract", "question"]
    source_query_id: str
    approved_by: str
    expires_at: datetime
    input_fingerprint: str
    output_fingerprint: str
    regression_case_id: str
