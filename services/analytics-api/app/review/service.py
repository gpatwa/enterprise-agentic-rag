"""Independent review workflow (ADS-055).

Reviews are append-only events. A decision is accepted only from a human reviewer who did not author,
request, or supply feedback for the subject, against the subject's exact current content, before the
review expires. Approving records a fact; it applies nothing, certifies nothing, and promotes nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.review.rules import ReviewError, check_reviewer, derive_state, is_automated
from app.review.store import ReviewStore, ReviewStoreError
from app.review.subjects import SubjectResolver
from packages.platform_contracts.review import (
    DEFAULT_REVIEW_TTL_HOURS,
    ReviewDecisionRequest,
    ReviewRecord,
    ReviewStatus,
)
from packages.platform_contracts.security import AnalyticsIdentity


class ReviewService:
    def __init__(
        self,
        store: ReviewStore,
        resolver: SubjectResolver,
        *,
        ttl: timedelta = timedelta(hours=DEFAULT_REVIEW_TTL_HOURS),
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.store, self.resolver, self.ttl, self.now = store, resolver, ttl, now

    # ---- operations ----

    def request_review(
        self, identity: AnalyticsIdentity, *, purpose: str, kind: str, subject_id: str, required_approvals: int = 1
    ) -> ReviewStatus:
        self._authorize(identity, purpose)
        subject = self.resolver.resolve(kind, subject_id, tenant_id=identity.tenant_id)
        for existing in self.store.for_subject(
            kind, subject_id, subject.content_fingerprint, tenant_id=identity.tenant_id
        ):
            status = self.status(existing.review_id, tenant_id=identity.tenant_id)
            if status.state in {"pending", "approved"}:
                return status  # one live review per exact content
        created = self.now()
        record = ReviewRecord(
            review_id=hashlib.sha256(
                f"{identity.tenant_id}:{kind}:{subject_id}:{subject.content_fingerprint}:{created.isoformat()}".encode()
            ).hexdigest()[:32],
            tenant_id=identity.tenant_id,
            purpose=purpose,
            subject=subject,
            requested_by=identity.user_id,
            required_approvals=required_approvals,
            created_at=created,
            expires_at=created + self.ttl,
        )
        self.store.create(record)
        self.store.append_event(record.tenant_id, record.review_id, "requested", identity.user_id, None, created)
        return self.status(record.review_id, tenant_id=record.tenant_id)

    def decide(self, identity: AnalyticsIdentity, *, review_id: str, request: ReviewDecisionRequest) -> ReviewStatus:
        self._authorize(identity, request.purpose)
        if is_automated(identity.user_id):
            raise ReviewError("automated_identity")
        record = self._record(review_id, identity.tenant_id, request.purpose)
        status = self.status(review_id, tenant_id=identity.tenant_id)
        if status.state == "expired":
            self._record_expiry(record, status)
            raise ReviewError("expired")
        if status.state != "pending":
            raise ReviewError("review_closed")
        if request.content_fingerprint != record.subject.content_fingerprint:
            raise ReviewError("fingerprint_mismatch")
        current = self.resolver.resolve(record.subject.kind, record.subject.subject_id, tenant_id=identity.tenant_id)
        if current.content_fingerprint != record.subject.content_fingerprint:
            raise ReviewError("subject_changed")
        deciders = tuple(e.actor for e in status.events if e.event_type in {"approved", "rejected"})
        violation = check_reviewer(
            user_id=identity.user_id,
            groups=identity.groups,
            contributors=tuple(set(record.subject.contributor_ids) | set(current.contributor_ids)),
            requested_by=record.requested_by,
            prior_deciders=deciders,
        )
        if violation:
            raise ReviewError(violation)
        self.store.append_event(
            record.tenant_id, review_id, request.decision, identity.user_id, request.note, self.now()
        )
        return self.status(review_id, tenant_id=record.tenant_id)

    def status(self, review_id: str, *, tenant_id: str) -> ReviewStatus:
        try:
            record = self.store.get(review_id, tenant_id=tenant_id)
        except ReviewStoreError as exc:
            raise ReviewError("review_not_found") from exc
        events = self.store.events(review_id, tenant_id=tenant_id)
        state, approvals, rejected_by = derive_state(record, events, self.now())
        return ReviewStatus(review=record, state=state, approvals=approvals, rejected_by=rejected_by, events=events)

    def expire_due(self, *, tenant_id: str) -> int:
        """Record an `expired` event for every review that ran out unfinished. Idempotent."""
        count = 0
        for record in self.store.pending_candidates(tenant_id=tenant_id):
            status = self.status(record.review_id, tenant_id=tenant_id)
            if status.state == "expired" and not any(e.event_type == "expired" for e in status.events):
                self._record_expiry(record, status)
                count += 1
        return count

    def is_approved(self, kind: str, subject_id: str, fingerprint: str, *, tenant_id: str) -> bool:
        """True only if a review of exactly this content reached its required independent approvals."""
        for record in self.store.for_subject(kind, subject_id, fingerprint, tenant_id=tenant_id):
            if self.status(record.review_id, tenant_id=tenant_id).state == "approved":
                return True
        return False

    # ---- internals ----

    @staticmethod
    def _authorize(identity: AnalyticsIdentity, purpose: str) -> None:
        if purpose not in identity.purposes:
            raise ReviewError("purpose_not_authorized")

    def _record(self, review_id: str, tenant_id: str, purpose: str) -> ReviewRecord:
        try:
            record = self.store.get(review_id, tenant_id=tenant_id)
        except ReviewStoreError as exc:
            raise ReviewError("review_not_found") from exc
        if record.purpose != purpose:
            raise ReviewError("review_not_found")
        return record

    def _record_expiry(self, record: ReviewRecord, status: ReviewStatus) -> None:
        if not any(e.event_type == "expired" for e in status.events):
            self.store.append_event(
                record.tenant_id, record.review_id, "expired", "system:review-expiry", None, self.now()
            )
