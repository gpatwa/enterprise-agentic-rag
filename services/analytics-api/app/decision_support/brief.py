"""A read-only brief for a paused review: what will run, what it costs, and a few mechanical checks.

It exists so a reviewer (a person) decides from facts rather than from a fingerprint, and so an AI assistant can prepare the same
brief. It never decides: `advisory.decision_authority` is always `none`, no review state changes, and no rows are included (a
paused run has not executed). Callers must be in the reviewer group or the review-assistant group; the assistant group can read
briefs but cannot decide a review, and no automated identity is ever in the reviewer group (the Entra verifier refuses app-only
tokens, and `caller_kind` refuses delegated and `agent:` identities from deciding).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.runtime.control_store import ControlStore, ControlStoreError
from packages.platform_contracts.review import REVIEWER_GROUP
from packages.platform_contracts.security import AnalyticsIdentity

REVIEW_ASSISTANT_GROUP = "analytics-review-assistant"


class BriefError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status, self.code = status, code
        super().__init__(code)


class Check(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    ok: bool
    detail: str


class Advisory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    suggestion: str  # looks_routine | needs_attention
    reasons: list[str]
    decision_authority: str = "none"


class ReviewBrief(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    review_id: str
    run_id: str
    state: str
    requested_by: str
    expires_at: datetime
    plan_fingerprint: str
    reason: str | None
    dataset: str | None
    metrics: list[str]
    group_by: list[str]
    filters: list[dict[str, Any]]
    time_range: dict[str, Any] | None
    dialect: str | None
    sql: str | None
    parameters: dict[str, Any]
    estimated_cost_units: float | None
    run_cost_limit: float | None
    checks: list[Check]
    advisory: Advisory


class ReviewBriefService:
    def __init__(
        self, control: ControlStore, plans: Any, *, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    ) -> None:
        self.control, self.plans, self.now = control, plans, now

    def _authorize(self, identity: AnalyticsIdentity) -> None:
        if not ({REVIEWER_GROUP, REVIEW_ASSISTANT_GROUP} & set(identity.groups)):
            raise BriefError(403, "reviewer_or_assistant_role_required")

    def pending(self, identity: AnalyticsIdentity, *, purpose: str) -> list[dict[str, Any]]:
        """The reviews waiting for a decision in the caller's tenant (identifiers and timing only; the brief has the facts)."""
        self._authorize(identity)
        return [
            {
                "review_id": r.review_id,
                "run_id": r.run_id,
                "requested_by": r.requested_by,
                "created_at": r.created_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
            }
            for r in self.control.list_pending_reviews(tenant_id=identity.tenant_id, purpose=purpose, now=self.now())
        ]

    def brief(self, identity: AnalyticsIdentity, *, purpose: str, run_id: str) -> ReviewBrief:
        if (
            purpose not in identity.purposes
            and REVIEWER_GROUP not in identity.groups
            and REVIEW_ASSISTANT_GROUP not in identity.groups
        ):
            raise BriefError(403, "purpose_not_authorized")
        if not ({REVIEWER_GROUP, REVIEW_ASSISTANT_GROUP} & set(identity.groups)):
            raise BriefError(403, "reviewer_or_assistant_role_required")
        try:
            state = self.control.load_run_state(run_id=run_id, tenant_id=identity.tenant_id, purpose=purpose)
        except ControlStoreError as exc:
            raise BriefError(404, "run_not_found") from exc
        approval = state.approval_state if isinstance(state.approval_state, dict) else {}
        review_id = approval.get("review_id")
        if state.status != "waiting_approval" or not review_id:
            raise BriefError(409, "run_not_awaiting_review")
        try:
            review = self.control.get_review(review_id, tenant_id=identity.tenant_id, purpose=purpose)
        except ControlStoreError as exc:
            raise BriefError(404, "review_not_found") from exc
        if review.state != "pending":
            raise BriefError(409, "review_not_pending")
        intent = state.intent or {}
        plan = None
        if state.compiled_plan_reference:
            try:
                plan = self.plans.get(identity.tenant_id, run_id, state.compiled_plan_reference)
            except LookupError:
                plan = None
        cost = state.cost_decision if isinstance(state.cost_decision, dict) else {}
        estimated = cost.get("estimated_cost_units")
        limit = float(state.budget.max_cost_units)
        checks = self._checks(intent, plan, estimated, limit, review, state)
        attention = [c for c in checks if not c.ok]
        return ReviewBrief(
            review_id=review.review_id,
            run_id=run_id,
            state=review.state,
            requested_by=review.requested_by,
            expires_at=review.expires_at,
            plan_fingerprint=review.plan_fingerprint,
            reason=approval.get("reason") or cost.get("reason"),
            dataset=intent.get("dataset_id"),
            metrics=[m.get("metric_id") for m in intent.get("metrics", [])],
            group_by=[g.get("dimension_id") for g in intent.get("group_by", [])],
            filters=[
                {"field": f.get("field_id"), "operator": f.get("operator"), "values": f.get("values")}
                for f in intent.get("filters", [])
            ],
            time_range=intent.get("time_range"),
            dialect=getattr(plan, "dialect", None),
            sql=getattr(plan, "sql", None),
            parameters=dict(getattr(plan, "parameters", {}) or {}) if plan is not None else {},
            estimated_cost_units=float(estimated) if estimated is not None else None,
            run_cost_limit=limit,
            checks=checks,
            advisory=Advisory(
                suggestion="needs_attention" if attention else "looks_routine",
                reasons=[f"{c.name}: {c.detail}" for c in attention],
            ),
        )

    def _checks(self, intent: dict, plan: Any, estimated: Any, limit: float, review: Any, state: Any) -> list[Check]:
        checks = [
            Check(
                name="plan_available",
                ok=plan is not None,
                detail="the compiled plan is stored"
                if plan is not None
                else "the compiled plan is missing: do not approve",
            ),
            Check(
                name="within_run_cost_limit",
                ok=estimated is None or float(estimated) <= limit,
                detail=f"estimated {estimated} of a limit of {limit:g}"
                if estimated is not None
                else "no estimate recorded",
            ),
            Check(
                name="time_range_bounded",
                ok=bool(intent.get("time_range")),
                detail="a time range is set" if intent.get("time_range") else "no time range: the query scans all time",
            ),
            Check(
                name="row_limit_set",
                ok=bool(intent.get("limit")) and int(intent.get("limit", 0)) <= 1_000,
                detail=f"limit {intent.get('limit')}",
            ),
            Check(
                name="not_about_to_expire",
                ok=(review.expires_at - self.now()).total_seconds() > 3_600,
                detail=f"expires {review.expires_at.isoformat()}",
            ),
            Check(
                name="requested_by_someone_else",
                ok=True,
                detail=f"requested by {review.requested_by}; the service refuses the requester's own decision",
            ),
        ]
        return checks
