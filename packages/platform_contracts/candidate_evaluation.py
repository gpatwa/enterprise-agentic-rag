"""Evaluation of an approved candidate against the pinned regression suites (ADS-056).

An evaluation is a recorded fact about one exact content fingerprint: which cases its change could affect
(targeted), what the full suites said, and a pass/fail verdict that rests only on approved thresholds. It
cannot change a threshold, a golden expectation, or a verdict rule, and it promotes nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EVALUATION_VERSION = "v1"
_HEX64 = r"^[0-9a-f]{64}$"
Verdict = Literal["passed", "failed"]
Scope = Literal["targeted", "full"]
_FAIL_CLOSED_REASONS = {"protected_file_changed", "unapproved_thresholds"}
SubjectKind = Literal["change_proposal", "prompt_candidate", "example_candidate"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Selection(_Frozen):
    """Which areas and semantic IDs the change can affect, and the golden cases that follow from them."""

    areas: tuple[str, ...] = Field(min_length=1)
    semantic_ids: tuple[str, ...] = ()
    targeted_case_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    sandbox: str = Field(min_length=1, max_length=500)


class SuiteOutcome(_Frozen):
    suite: str = Field(min_length=1, max_length=64)
    scope: Scope
    passed: bool
    total: int = Field(ge=0)
    failed: tuple[str, ...] = ()
    thresholds_approved: bool = True

    @model_validator(mode="after")
    def consistent(self) -> "SuiteOutcome":
        if self.passed and self.failed:
            raise ValueError("a passing suite has no failures")
        return self


class EvaluationRecord(_Frozen):
    evaluation_version: Literal["v1"] = EVALUATION_VERSION
    evaluation_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=255)
    subject_fingerprint: str = Field(pattern=_HEX64)
    selection: Selection
    outcomes: tuple[SuiteOutcome, ...] = Field(min_length=1)
    verdict: Verdict
    reason: str | None = Field(default=None, max_length=255)
    protected_digest: str = Field(pattern=_HEX64)
    evaluator: Literal["system:evaluator"] = "system:evaluator"
    created_at: datetime
    content_fingerprint: str = Field(pattern=_HEX64)

    @model_validator(mode="after")
    def verdict_follows_outcomes(self) -> "EvaluationRecord":
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        everything_passed = (
            all(o.passed for o in self.outcomes)
            and any(o.scope == "full" for o in self.outcomes)
            and any(o.scope == "targeted" for o in self.outcomes)
        )
        if self.verdict == "passed":
            if not everything_passed:
                raise ValueError("a verdict is 'passed' only if targeted and full suites all passed")
            if not all(o.thresholds_approved for o in self.outcomes):
                raise ValueError("a verdict may only rest on approved thresholds")
        elif everything_passed and self.reason not in _FAIL_CLOSED_REASONS:
            raise ValueError("a clean run fails only for a named fail-closed reason")
        return self
