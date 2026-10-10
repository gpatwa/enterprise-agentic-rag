"""Deterministic planning and human-review contracts for governed analytics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.analytics_v2 import AnalyticsProvenance


class AnalyticsContextCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=512)
    asset_type: Literal["dataset", "metric", "dimension", "semantic_contract", "catalog"]
    version: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class AnalyticsPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1, max_length=255)
    intent: AnalyticalIntent
    context: list[AnalyticsContextCitation] = Field(min_length=1, max_length=50)
    provenance: list[AnalyticsProvenance] = Field(default_factory=list)
    planner_version: str = Field(min_length=1, max_length=255)


class AnalyticsAmbiguity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["metric", "dataset", "grain", "time", "filter"]
    prompt: str = Field(min_length=1, max_length=2_000)
    candidate_ids: list[str] = Field(min_length=1, max_length=20)


class AnalyticsClarificationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1, max_length=255)
    request_fingerprint: str = Field(min_length=1, max_length=255)
    ambiguities: list[AnalyticsAmbiguity] = Field(min_length=1, max_length=5)
    run_id: str | None = Field(default=None, min_length=1, max_length=255)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=255)
    purpose: str | None = Field(default=None, min_length=1, max_length=255)
    selected_choices: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    continuation_count: int = Field(default=0, ge=0, le=2)


class AnalyticsReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1, max_length=255)
    query_id: str = Field(min_length=1, max_length=255)
    state: Literal["pending", "approved", "rejected", "expired", "superseded"] = "pending"
    reason_codes: list[str] = Field(min_length=1, max_length=10)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime


class DurableReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: str = Field(min_length=1, max_length=255)
    run_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    plan_fingerprint: str = Field(min_length=64, max_length=128)
    requested_by: str = Field(min_length=1, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    state: Literal["pending", "approved", "rejected", "expired"] = "pending"
    resolved_by: str | None = Field(default=None, max_length=255)
    resolved_at: datetime | None = None
    resolution_note: str | None = Field(default=None, max_length=2_000)
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "DurableReviewDecision":
        for value in (self.created_at, self.expires_at, self.resolved_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("review timestamps must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("review expiry must follow creation")
        if self.state in {"approved", "rejected"} and (not self.resolved_by or not self.resolved_at):
            raise ValueError("resolved decisions require reviewer identity and timestamp")
        return self


class SavedAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    contract_id: str = Field(min_length=1, max_length=255)
    contract_version: str = Field(min_length=1, max_length=255)
    intent: AnalyticalIntent
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
