"""Additive v2 public outcomes for governed analytics requests.

The v1 request and response models remain supported. These v2 contracts model
the outcome state only; routing, planning, persistence, and policy enforcement
are deliberately deferred to later enterprise analytics milestones.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class AnalyticsOutcomeBase(BaseModel):
    """Fields carried by every externally visible v2 analytics outcome."""

    contract_version: Literal["v2"] = "v2"
    query_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    user_id: str = Field(min_length=1, max_length=255)
    dataset: str = Field(min_length=1, max_length=100)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = Field(default=None, ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list)


class AnalyticsFilterEvidence(BaseModel):
    field_id: str = Field(min_length=1, max_length=255)
    operator: str = Field(min_length=1, max_length=64)
    value: str | int | float | bool | None = None


class AnalyticsProvenance(BaseModel):
    """A versioned context asset cited by an answer without exposing raw data."""

    asset_id: str = Field(min_length=1, max_length=255)
    asset_type: Literal["dataset", "metric", "dimension", "semantic_contract", "catalog"]
    version: str | None = Field(default=None, max_length=255)
    retrieved_at: datetime | None = None


class AnalyticsPolicyDecision(BaseModel):
    decision_id: str = Field(min_length=1, max_length=255)
    effect: Literal["allow", "deny", "review"]
    policy_version: str | None = Field(default=None, max_length=255)
    enforced_filter_ids: list[str] = Field(default_factory=list)


class AnalyticsReviewReference(BaseModel):
    review_id: str = Field(min_length=1, max_length=255)
    state: Literal["pending", "approved", "rejected", "expired"]


class AnalyticsAnswerEvidence(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    semantic_contract_version: str | None = Field(default=None, max_length=255)
    metric_ids: list[str] = Field(default_factory=list)
    dimension_ids: list[str] = Field(default_factory=list)
    source_asset_ids: list[str] = Field(default_factory=list)
    provenance: list[AnalyticsProvenance] = Field(default_factory=list)
    filters: list[AnalyticsFilterEvidence] = Field(default_factory=list)
    generated_sql: str | None = None
    result_fingerprint: str | None = Field(default=None, max_length=255)
    data_freshness_at: datetime | None = None
    model_version: str | None = Field(default=None, max_length=255)
    prompt_version: str | None = Field(default=None, max_length=255)
    policy_decision: AnalyticsPolicyDecision | None = None


class AnalyticsClaim(BaseModel):
    """One sentence of explanation and the fixed result-cell/semantic IDs it cites."""

    text: str = Field(min_length=1, max_length=400)
    cites: list[str] = Field(min_length=1, max_length=20)


class AnalyticsResultTable(BaseModel):
    columns: list[str] = Field(max_length=50)
    rows: list[list[str | int | float | bool | None]] = Field(max_length=1_000)
    row_count: int = Field(ge=0)


class AnalyticsVisualization(BaseModel):
    """Data-free chart spec: column indexes into the result table, bound to semantic IDs."""

    kind: Literal["stat", "line", "bar", "table"]
    x_column: int | None = Field(default=None, ge=0)
    y_columns: list[int] = Field(default_factory=list)
    semantic_ids: list[str] = Field(default_factory=list)
    row_limit: int = Field(ge=1)


class AnalyticsAnswerOutcome(AnalyticsOutcomeBase):
    outcome: Literal["answer"] = "answer"
    answer: str = Field(min_length=1)
    explanation_status: Literal["grounded", "evidence_only"] | None = None
    claims: list[AnalyticsClaim] = Field(default_factory=list, max_length=8)
    result: AnalyticsResultTable | None = None
    visualization: AnalyticsVisualization | None = None
    evidence: AnalyticsAnswerEvidence = Field(default_factory=AnalyticsAnswerEvidence)
    review: AnalyticsReviewReference | None = None


class AnalyticsClarificationChoice(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)


class AnalyticsClarificationQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1, max_length=2_000)
    choices: list[AnalyticsClarificationChoice] = Field(default_factory=list, max_length=8)
    free_text_allowed: bool = True


class AnalyticsClarifyOutcome(AnalyticsOutcomeBase):
    outcome: Literal["clarify"] = "clarify"
    questions: list[AnalyticsClarificationQuestion] = Field(min_length=1, max_length=5)


class AnalyticsRefuseOutcome(AnalyticsOutcomeBase):
    outcome: Literal["refuse"] = "refuse"
    reason_code: Literal[
        "insufficient_context",
        "unauthorized",
        "unsupported_request",
        "stale_metadata",
        "policy_restricted",
    ]
    explanation: str = Field(min_length=1, max_length=2_000)
    remediation: str | None = Field(default=None, max_length=2_000)


class AnalyticsReviewOutcome(AnalyticsOutcomeBase):
    outcome: Literal["review"] = "review"
    review_id: str = Field(min_length=1, max_length=255)
    risk_reasons: list[str] = Field(min_length=1, max_length=10)
    expires_at: datetime
    allowed_actions: list[Literal["approve", "edit", "reject"]] = Field(min_length=1)


class AnalyticsFailedOutcome(AnalyticsOutcomeBase):
    outcome: Literal["failed"] = "failed"
    error_code: Literal[
        "planner_unavailable",
        "executor_unavailable",
        "query_timeout",
        "internal_error",
    ]
    message: str = Field(min_length=1, max_length=2_000)
    retryable: bool


AnalyticsV2Outcome = Annotated[
    AnalyticsAnswerOutcome
    | AnalyticsClarifyOutcome
    | AnalyticsRefuseOutcome
    | AnalyticsReviewOutcome
    | AnalyticsFailedOutcome,
    Field(discriminator="outcome"),
]


class AnalyticsV2Response(RootModel[AnalyticsV2Outcome]):
    """Discriminated v2 outcome envelope suitable for public API responses."""

    root: AnalyticsV2Outcome
