"""EA-034 to EA-036 evidence review and replay safety tests."""
from datetime import datetime, timedelta, timezone

import pytest

from app.governance import ReviewQueue, ReviewStateError
from packages.platform_contracts.analytics_planning import AnalyticsReviewRequest


def review(expires_in=60):
    return AnalyticsReviewRequest(
        review_id="r1",
        query_id="q1",
        reason_codes=["uncertified_metadata"],
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    )


def test_review_queue_allows_approve_once_and_is_idempotently_readable():
    queue = ReviewQueue()
    queue.create(review())
    assert queue.transition("r1", "approved").state == "approved"
    assert queue.get("r1").state == "approved"
    with pytest.raises(ReviewStateError, match="not allowed"):
        queue.transition("r1", "rejected")


def test_expired_review_cannot_be_approved():
    queue = ReviewQueue()
    queue.create(review(-1))
    assert queue.get("r1").state == "expired"
    with pytest.raises(ReviewStateError, match="not allowed"):
        queue.transition("r1", "approved")
