"""Pure separation-of-duties rules and state derivation for reviews (ADS-055)."""

from __future__ import annotations

from datetime import datetime

from packages.platform_contracts.review import REVIEWER_GROUP, ReviewEvent, ReviewRecord, ReviewState

AUTOMATED_PREFIXES = ("system:", "model:", "agent:", "service:")


class ReviewError(Exception):
    """A review operation was refused; `code` is stable and carries no content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def is_automated(user_id: str) -> bool:
    return user_id.startswith(AUTOMATED_PREFIXES)


def derive_state(
    record: ReviewRecord, events: tuple[ReviewEvent, ...], now: datetime
) -> tuple[ReviewState, tuple[str, ...], str | None]:
    """(state, approvers, rejecting reviewer). A rejection is terminal; approvals need distinct reviewers."""
    approvals: list[str] = []
    for event in events:
        if event.event_type == "rejected":
            return "rejected", tuple(approvals), event.actor
        if event.event_type == "approved" and event.actor not in approvals:
            approvals.append(event.actor)
    if len(approvals) >= record.required_approvals:
        return "approved", tuple(approvals), None
    if any(event.event_type == "expired" for event in events) or now >= record.expires_at:
        return "expired", tuple(approvals), None
    return "pending", tuple(approvals), None


def check_reviewer(
    *,
    user_id: str,
    groups: list[str],
    contributors: tuple[str, ...],
    requested_by: str,
    prior_deciders: tuple[str, ...],
) -> str | None:
    """The first separation-of-duties violation, or None. Order is fixed so the code is stable."""
    if is_automated(user_id):
        return "automated_identity"
    if REVIEWER_GROUP not in groups:
        return "not_a_reviewer"
    if user_id in contributors:
        return "is_contributor"
    if user_id == requested_by:
        return "is_requester"
    if user_id in prior_deciders:
        return "already_decided_by_reviewer"
    return None
