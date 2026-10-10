"""Structured feedback on a terminal analytics run (ADS-050).

Feedback is a recorded fact, not an instruction: it binds to one sealed evidence envelope and has
no authority to change goldens, policy, prompts, or context. The correction, when present, can only
name certified semantic IDs; it can never carry SQL. The note is untrusted free text.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FEEDBACK_VERSION = "v1"
_HEX64 = r"^[0-9a-f]{64}$"
_SEMANTIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$")

Verdict = Literal["correct", "incorrect", "partially_correct", "unsafe"]
ReasonCode = Literal[
    "wrong_metric",
    "wrong_filter",
    "wrong_time_range",
    "wrong_grain",
    "missing_context",
    "stale_data",
    "policy_concern",
    "unclear_explanation",
    "other",
]
CorrectionTarget = Literal["metric", "dimension", "filter_field", "time_dimension"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposedCorrection(_Strict):
    """A suggestion naming one certified semantic ID; it is only ever validated, never executed."""

    target: CorrectionTarget
    semantic_id: str = Field(min_length=1, max_length=255)

    @field_validator("semantic_id")
    @classmethod
    def identifiers_only(cls, value: str) -> str:
        if not _SEMANTIC_ID.match(value):
            raise ValueError("corrections may only name a semantic ID, not an expression or SQL")
        return value


class FeedbackSubmission(_Strict):
    """What a caller may send; everything about the run is bound by the server."""

    purpose: str = Field(min_length=1, max_length=255)
    verdict: Verdict
    reason_code: ReasonCode
    correction: ProposedCorrection | None = None
    note: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def reason_matches_verdict(self) -> "FeedbackSubmission":
        if self.verdict == "correct" and (self.correction or self.reason_code != "other"):
            raise ValueError("a 'correct' verdict carries no correction and uses reason_code 'other'")
        return self


class FeedbackRecord(BaseModel):
    """The stored, immutable record. Fingerprints come from the sealed evidence envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feedback_version: Literal["v1"] = FEEDBACK_VERSION
    feedback_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    run_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    submitted_by: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=8, max_length=128)
    verdict: Verdict
    reason_code: ReasonCode
    correction: ProposedCorrection | None = None
    note: str | None = Field(default=None, max_length=2_000)
    terminal_kind: str = Field(min_length=1, max_length=32)
    evidence_fingerprint: str = Field(pattern=_HEX64)
    result_fingerprint: str | None = Field(default=None, pattern=_HEX64)
    intent_fingerprint: str | None = Field(default=None, pattern=_HEX64)
    semantic_contract: str | None = Field(default=None, max_length=512)
    context_snapshot_id: str = Field(min_length=1, max_length=255)
    submission_fingerprint: str = Field(pattern=_HEX64)
    created_at: datetime

    @model_validator(mode="after")
    def timezone_aware(self) -> "FeedbackRecord":
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return self


class FeedbackReceipt(_Strict):
    feedback_id: str
    run_id: str
    evidence_fingerprint: str
    created: bool
