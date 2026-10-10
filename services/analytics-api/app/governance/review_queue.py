"""Small explicit state machine for exploratory and high-risk analytics reviews."""
from __future__ import annotations

from datetime import datetime, timezone

from packages.platform_contracts.analytics_planning import AnalyticsReviewRequest


class ReviewStateError(ValueError):
    pass


class ReviewQueue:
    def __init__(self):
        self._items: dict[str, AnalyticsReviewRequest] = {}

    def create(self, request: AnalyticsReviewRequest) -> AnalyticsReviewRequest:
        if request.review_id in self._items:
            raise ReviewStateError("review already exists")
        self._items[request.review_id] = request
        return request

    def get(self, review_id: str) -> AnalyticsReviewRequest:
        try:
            request = self._items[review_id]
        except KeyError as exc:
            raise ReviewStateError("review was not found") from exc
        if request.state == "pending" and request.expires_at <= datetime.now(timezone.utc):
            request = request.model_copy(update={"state": "expired"})
            self._items[review_id] = request
        return request

    def transition(self, review_id: str, state: str) -> AnalyticsReviewRequest:
        request = self.get(review_id)
        if request.state != "pending" or state not in {"approved", "rejected"}:
            raise ReviewStateError("review transition is not allowed")
        updated = request.model_copy(update={"state": state})
        self._items[review_id] = updated
        return updated
