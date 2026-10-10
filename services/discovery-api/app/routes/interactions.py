"""Typed local interaction, feedback, and explanation API contracts."""
from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.audit.ranking import RankingAuditRecord, RankingAuditWriter
from app.domain.models import ConsentState
from app.events.ingestion import EventReceipt, InteractionIngestion
from app.events.models import (
    DismissPayload,
    EventType,
    InteractionEvent,
    InteractionEventBatch,
    ReportPayload,
)
from packages.platform_contracts.discovery import ImpressionToken

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_CODE = r"^[a-z0-9][a-z0-9._:-]{0,63}$"
_VERSION = "imd-interactions-v1"
_MAX_BATCH = 100


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FeedbackType(str, Enum):
    DISMISS = "dismiss"
    REPORT = "report"


class FeedbackReason(str, Enum):
    NOT_INTERESTED = "not_interested"
    ALREADY_SEEN = "already_seen"
    TOO_COMPLEX = "too_complex"
    NOT_RELEVANT = "not_relevant"
    SAFETY = "safety"
    COPYRIGHT = "copyright"
    SPAM = "spam"
    MISLEADING = "misleading"
    OTHER = "other"


class InteractionSubmission(_ApiModel):
    """A tenant- and request-scoped batch of already typed events."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    user_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    events: tuple[InteractionEvent, ...] = Field(min_length=1, max_length=_MAX_BATCH)


class InteractionResponse(_ApiModel):
    schema_version: str = _VERSION
    accepted: int = Field(ge=0, le=_MAX_BATCH)
    already_present: int = Field(ge=0, le=_MAX_BATCH)
    rejected: int = Field(ge=0, le=_MAX_BATCH)
    receipts: tuple[EventReceipt, ...] = Field(max_length=_MAX_BATCH)


class FeedbackSubmission(_ApiModel):
    """Bounded feedback input; free-form comments and private context are excluded."""

    event_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    user_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    experience_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    occurred_at: datetime
    synthetic: bool
    consent_state: ConsentState
    impression_token: ImpressionToken
    feedback_type: FeedbackType
    reason: FeedbackReason

    @model_validator(mode="after")
    def validate_feedback(self) -> "FeedbackSubmission":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.feedback_type is FeedbackType.DISMISS and self.reason not in {
            FeedbackReason.NOT_INTERESTED,
            FeedbackReason.ALREADY_SEEN,
            FeedbackReason.TOO_COMPLEX,
            FeedbackReason.NOT_RELEVANT,
            FeedbackReason.OTHER,
        }:
            raise ValueError("dismiss feedback requires a dismiss reason")
        if self.feedback_type is FeedbackType.REPORT and self.reason not in {
            FeedbackReason.SAFETY,
            FeedbackReason.COPYRIGHT,
            FeedbackReason.SPAM,
            FeedbackReason.MISLEADING,
            FeedbackReason.OTHER,
        }:
            raise ValueError("report feedback requires a report reason")
        return self


class FeedbackResponse(_ApiModel):
    schema_version: str = _VERSION
    receipt: EventReceipt


class ExplanationResponse(_ApiModel):
    """Safe ranking explanation; it contains labels, never raw ranking inputs."""

    schema_version: str = _VERSION
    explanation_id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    decision_ref: str = Field(min_length=1, max_length=255, pattern=_ID)
    outcome: str = Field(min_length=1, max_length=32, pattern=_CODE)
    fallback: bool
    reason_codes: tuple[str, ...] = Field(max_length=16)
    component_versions: tuple[str, ...] = Field(max_length=32)
    evidence: tuple[str, ...] = Field(max_length=32)


class LocalInteractionService:
    """Compose deterministic in-memory ingestion and audit lookup contracts."""

    def __init__(
        self,
        *,
        ingestion: InteractionIngestion | None = None,
        audit: RankingAuditWriter | None = None,
    ) -> None:
        self._ingestion = ingestion or InteractionIngestion()
        self._audit = audit or RankingAuditWriter()

    def submit(self, request: InteractionSubmission) -> InteractionResponse:
        batch = InteractionEventBatch(batch_id=_digest(request.request_id), events=request.events)
        result = self._ingestion.ingest(
            batch,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            request_id=request.request_id,
        )
        return InteractionResponse(
            accepted=result.accepted,
            already_present=result.already_present,
            rejected=result.rejected,
            receipts=result.receipts,
        )

    def submit_feedback(self, request: FeedbackSubmission) -> FeedbackResponse:
        payload = (
            DismissPayload(reason=request.reason.value)
            if request.feedback_type is FeedbackType.DISMISS
            else ReportPayload(category=request.reason.value)
        )
        event = InteractionEvent(
            event_id=request.event_id,
            event_type=EventType.DISMISS if request.feedback_type is FeedbackType.DISMISS else EventType.REPORT,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            experience_id=request.experience_id,
            request_id=request.request_id,
            occurred_at=request.occurred_at,
            synthetic=request.synthetic,
            consent_state=request.consent_state,
            impression_token=request.impression_token,
            payload=payload,
        )
        result = self.submit(
            InteractionSubmission(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                request_id=request.request_id,
                events=(event,),
            )
        )
        return FeedbackResponse(receipt=result.receipts[0])

    def explain(self, decision_ref: str) -> ExplanationResponse:
        if not isinstance(decision_ref, str) or not decision_ref.strip():
            raise ValueError("decision_ref must be non-empty")
        record = next((item for item in self._audit.records if item.event_id == decision_ref), None)
        if record is None:
            raise KeyError("unknown decision reference")
        return _explanation(record)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _explanation(record: RankingAuditRecord) -> ExplanationResponse:
    return ExplanationResponse(
        explanation_id=_digest(record.event_id),
        decision_ref=record.event_id,
        outcome=record.outcome.value,
        fallback=record.fallback,
        reason_codes=record.reason_codes,
        component_versions=record.component_versions,
        evidence=record.evidence,
    )


router = APIRouter()
_service = LocalInteractionService()


@router.post("/interactions", response_model=InteractionResponse)
def submit_interactions(request: InteractionSubmission) -> InteractionResponse:
    return _service.submit(request)


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(request: FeedbackSubmission) -> FeedbackResponse:
    return _service.submit_feedback(request)


@router.get("/explanations/{decision_ref}", response_model=ExplanationResponse)
def get_explanation(decision_ref: str) -> ExplanationResponse:
    try:
        return _service.explain(decision_ref)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="explanation_not_found") from exc


__all__ = [
    "ExplanationResponse",
    "FeedbackReason",
    "FeedbackSubmission",
    "FeedbackType",
    "InteractionResponse",
    "InteractionSubmission",
    "LocalInteractionService",
    "get_explanation",
    "router",
    "submit_feedback",
    "submit_interactions",
]
