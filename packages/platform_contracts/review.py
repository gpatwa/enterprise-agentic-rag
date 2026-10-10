"""Independent review of proposals and candidates (ADS-055).

A review is an append-only event log bound to one subject at one content fingerprint. An approval is a
recorded fact about that exact content; it applies nothing and certifies nothing by itself. Separation of
duties is enforced by the service from these records: nobody who authored, requested, or supplied the
feedback behind a subject can approve it, and neither can a system or model identity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REVIEW_VERSION = "v1"
REVIEWER_GROUP = "analytics-reviewer"
DEFAULT_REVIEW_TTL_HOURS = 72
_HEX64 = r"^[0-9a-f]{64}$"

SubjectKind = Literal["change_proposal", "prompt_candidate", "example_candidate"]
EventType = Literal["requested", "approved", "rejected", "expired"]
ReviewState = Literal["pending", "approved", "rejected", "expired"]
Decision = Literal["approved", "rejected"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewSubject(_Frozen):
    """What is being reviewed, at which content, and everyone who contributed to it."""

    kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=255)
    content_fingerprint: str = Field(pattern=_HEX64)
    contributor_ids: tuple[str, ...] = Field(min_length=1)


class ReviewDecisionRequest(_Frozen):
    purpose: str = Field(min_length=1, max_length=255)
    decision: Decision
    content_fingerprint: str = Field(pattern=_HEX64)
    note: str | None = Field(default=None, max_length=2_000)


class ReviewEvent(_Frozen):
    seq: int = Field(ge=1)
    event_type: EventType
    actor: str = Field(min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=2_000)
    created_at: datetime

    @model_validator(mode="after")
    def aware(self) -> "ReviewEvent":
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return self


class ReviewRecord(_Frozen):
    review_version: Literal["v1"] = REVIEW_VERSION
    review_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    subject: ReviewSubject
    requested_by: str = Field(min_length=1, max_length=255)
    required_approvals: int = Field(default=1, ge=1, le=3)
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def ordered(self) -> "ReviewRecord":
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("review timestamps must include a timezone")
        if self.expires_at <= self.created_at:
            raise ValueError("a review expires after it is requested")
        return self


class ReviewStatus(_Frozen):
    """The derived state of a review, with the audit trail it was derived from."""

    review: ReviewRecord
    state: ReviewState
    approvals: tuple[str, ...] = ()
    rejected_by: str | None = None
    events: tuple[ReviewEvent, ...] = ()
