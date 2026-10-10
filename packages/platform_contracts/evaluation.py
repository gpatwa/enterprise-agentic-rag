"""Pinned evaluation and release-gate contracts."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EvaluationCase(BaseModel):
    case_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=3, max_length=2_000)
    expected_outcome: Literal["answer", "clarify", "refuse", "review"]
    expected_metric_ids: list[str] = Field(default_factory=list)
    expected_dataset_id: str | None = None
    expected_sql_fingerprint: str | None = None
    adversarial_type: Literal["none", "ambiguity", "refusal", "security", "cost"] = "none"
    expected_reason_code: str | None = None


class EvaluationSuite(BaseModel):
    suite_version: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    cases: list[EvaluationCase] = Field(min_length=1, max_length=10_000)
    fixture_digest: str = Field(min_length=1, max_length=255)


class EvaluationResult(BaseModel):
    case_id: str
    outcome: str
    metric_match: bool
    dataset_match: bool
    sql_match: bool | None = None
    passed: bool


class ReleaseGateReport(BaseModel):
    suite_version: str
    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    blocked: bool
    reasons: list[str] = Field(default_factory=list)
