"""Consented, bounded admission for immutable discovery interaction events."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ConsentState
from app.events.models import EventType, InteractionEvent, InteractionEventBatch


class _IngestionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RejectionReason(str, Enum):
    BATCH_TENANT_MISMATCH = "batch_tenant_mismatch"
    USER_SCOPE_MISMATCH = "user_scope_mismatch"
    REQUEST_SCOPE_MISMATCH = "request_scope_mismatch"
    EVENT_VERSION_UNSUPPORTED = "event_version_unsupported"
    CONSENT_REQUIRED = "consent_required"
    TIMESTAMP_SKEW = "timestamp_skew"
    IMPRESSION_LINEAGE_INVALID = "impression_lineage_invalid"
    SYNTHETIC_MARKER_INVALID = "synthetic_marker_invalid"
    EVENT_ID_CONFLICT = "event_id_conflict"
    DUPLICATE_IN_BATCH = "duplicate_in_batch"
    INVALID_EVENT = "invalid_event"


class ReceiptStatus(str, Enum):
    ACCEPTED = "accepted"
    ALREADY_PRESENT = "already_present"
    REJECTED = "rejected"


class EventReceipt(_IngestionModel):
    """A bounded receipt that contains no raw payload or private identifiers."""

    event_ref: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    status: ReceiptStatus
    reason: RejectionReason | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> "EventReceipt":
        if self.status is ReceiptStatus.REJECTED and self.reason is None:
            raise ValueError("rejected receipts require a reason")
        if self.status is not ReceiptStatus.REJECTED and self.reason is not None:
            raise ValueError("accepted receipts cannot carry a rejection reason")
        return self


class IngestionResult(_IngestionModel):
    schema_version: str = "v1"
    accepted: int = Field(ge=0, le=1_000)
    already_present: int = Field(ge=0, le=1_000)
    rejected: int = Field(ge=0, le=1_000)
    receipts: tuple[EventReceipt, ...] = Field(max_length=1_000)

    @model_validator(mode="after")
    def validate_counts(self) -> "IngestionResult":
        if self.accepted + self.already_present + self.rejected != len(self.receipts):
            raise ValueError("ingestion counts must match receipts")
        return self


def _event_ref(event: InteractionEvent) -> str:
    """Hash the tenant and event identity so receipts cannot disclose raw values."""
    encoded = f"{event.tenant_id}:{event.event_id}".encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint(event: InteractionEvent) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class InteractionIngestion:
    """Admit typed events once, without mutating an existing replay."""

    def __init__(
        self,
        *,
        max_timestamp_skew: timedelta = timedelta(minutes=5),
        require_synthetic: bool = False,
    ) -> None:
        if max_timestamp_skew < timedelta(0) or max_timestamp_skew > timedelta(days=1):
            raise ValueError("max_timestamp_skew must be between zero and one day")
        self._max_timestamp_skew = max_timestamp_skew
        self._require_synthetic = require_synthetic
        self._events: dict[tuple[str, str], str] = {}
        self._lock = Lock()

    def ingest(
        self,
        batch: InteractionEventBatch,
        *,
        tenant_id: str,
        user_id: str,
        request_id: str,
        received_at: datetime | None = None,
    ) -> IngestionResult:
        """Validate and append a batch with deterministic replay semantics."""
        now = received_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")

        receipts: list[EventReceipt] = []
        pending: list[tuple[InteractionEvent, str]] = []
        seen: set[tuple[str, str]] = set()
        for event in batch.events:
            reason = self._validate_event(
                event,
                batch_tenant_id=tenant_id,
                user_id=user_id,
                request_id=request_id,
                received_at=now,
            )
            key = (event.tenant_id, event.event_id)
            if reason is not None:
                receipts.append(EventReceipt(event_ref=_event_ref(event), status=ReceiptStatus.REJECTED, reason=reason))
                continue
            if key in seen:
                receipts.append(EventReceipt(event_ref=_event_ref(event), status=ReceiptStatus.REJECTED, reason=RejectionReason.DUPLICATE_IN_BATCH))
                continue
            seen.add(key)
            pending.append((event, _fingerprint(event)))

        with self._lock:
            for event, fingerprint in pending:
                key = (event.tenant_id, event.event_id)
                existing = self._events.get(key)
                if existing is None:
                    self._events[key] = fingerprint
                    receipts.append(EventReceipt(event_ref=_event_ref(event), status=ReceiptStatus.ACCEPTED))
                elif existing == fingerprint:
                    receipts.append(EventReceipt(event_ref=_event_ref(event), status=ReceiptStatus.ALREADY_PRESENT))
                else:
                    receipts.append(EventReceipt(event_ref=_event_ref(event), status=ReceiptStatus.REJECTED, reason=RejectionReason.EVENT_ID_CONFLICT))

        accepted = sum(receipt.status is ReceiptStatus.ACCEPTED for receipt in receipts)
        already_present = sum(receipt.status is ReceiptStatus.ALREADY_PRESENT for receipt in receipts)
        return IngestionResult(
            accepted=accepted,
            already_present=already_present,
            rejected=len(receipts) - accepted - already_present,
            receipts=tuple(receipts),
        )

    def _validate_event(
        self,
        event: InteractionEvent,
        *,
        batch_tenant_id: str,
        user_id: str,
        request_id: str,
        received_at: datetime,
    ) -> RejectionReason | None:
        if event.tenant_id != batch_tenant_id:
            return RejectionReason.BATCH_TENANT_MISMATCH
        if event.user_id != user_id:
            return RejectionReason.USER_SCOPE_MISMATCH
        if event.request_id != request_id:
            return RejectionReason.REQUEST_SCOPE_MISMATCH
        if event.event_version != "v1":
            return RejectionReason.EVENT_VERSION_UNSUPPORTED
        if not isinstance(event.synthetic, bool):
            return RejectionReason.SYNTHETIC_MARKER_INVALID
        if self._require_synthetic and not event.synthetic:
            return RejectionReason.SYNTHETIC_MARKER_INVALID
        if event.event_type is not EventType.ORGANIC_NAVIGATION and event.consent_state is not ConsentState.PERSONALIZATION_ALLOWED:
            return RejectionReason.CONSENT_REQUIRED
        if abs(received_at - event.occurred_at) > self._max_timestamp_skew:
            return RejectionReason.TIMESTAMP_SKEW
        token = event.impression_token
        if event.event_type is not EventType.ORGANIC_NAVIGATION:
            if token is None or event.occurred_at < token.issued_at or event.occurred_at > token.expires_at:
                return RejectionReason.IMPRESSION_LINEAGE_INVALID
        return None


def ingest_events(
    events: Iterable[InteractionEvent],
    *,
    tenant_id: str,
    user_id: str,
    request_id: str,
    received_at: datetime | None = None,
) -> IngestionResult:
    """Convenience boundary for callers that already have typed events."""
    batch = InteractionEventBatch(batch_id="ingestion-batch", events=tuple(events))
    return InteractionIngestion().ingest(
        batch, tenant_id=tenant_id, user_id=user_id, request_id=request_id, received_at=received_at
    )
