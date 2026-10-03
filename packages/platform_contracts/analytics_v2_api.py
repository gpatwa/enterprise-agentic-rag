"""Request and response envelopes for the governed `/api/v2/analytics` endpoints (ADS-045)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.platform_contracts.analytics_v2 import AnalyticsV2Outcome


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalyzeRequest(_Strict):
    request_text: str = Field(min_length=3, max_length=2_000)
    purpose: str = Field(min_length=1, max_length=255)


class ClarifyRequest(_Strict):
    purpose: str = Field(min_length=1, max_length=255)
    ambiguity_code: Literal["metric", "dataset", "grain", "time", "filter"]
    selected_id: str = Field(min_length=1, max_length=255)


class ReviewDecisionRequest(_Strict):
    purpose: str = Field(min_length=1, max_length=255)
    decision: Literal["approved", "rejected"]
    plan_fingerprint: str = Field(min_length=64, max_length=128)
    note: str | None = Field(default=None, max_length=2_000)


RunState = Literal["running", "waiting_clarification", "waiting_review", "terminal"]


class AnalyzeRunResponse(_Strict):
    """`outcome` is absent only while the run is still executing on another worker."""

    run_id: str = Field(min_length=1, max_length=255)
    state: RunState
    outcome: AnalyticsV2Outcome | None = None
