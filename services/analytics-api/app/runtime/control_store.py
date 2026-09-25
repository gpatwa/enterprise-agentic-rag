"""Transactional primitives for the bounded analytics agent control store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, text

from packages.platform_contracts.agent_runtime import AgentRunState, CancellationRequest, Transition
from packages.platform_contracts.analytics_planning import DurableReviewDecision
from packages.platform_contracts.security import AnalyticsIdentity


class ControlStoreError(RuntimeError):
    """Base error for durable run-control failures."""


class LeaseUnavailable(ControlStoreError):
    """Raised when another live worker owns a run lease."""


class StaleWorkerError(ControlStoreError):
    """Raised when a worker loses its compare-and-set or fencing race."""


@dataclass(frozen=True)
class Lease:
    run_id: str
    tenant_id: str
    purpose: str
    owner_id: str
    lease_token: str
    fencing_seq: int
    expires_at: datetime


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _payload(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("control-store timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


class ControlStore:
    """Small repository adapter that keeps projection and evidence writes atomic."""

    def __init__(self, engine: Engine, *, lease_seconds: int = 30) -> None:
        self.engine = engine
        self.lease_seconds = lease_seconds

    def create_run(self, state: AgentRunState) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO analytics_agent_runs
                    (run_id, tenant_id, purpose, graph_version, state_version, status, current_node,
                     state_payload, transition_seq, lease_fencing_seq, cancel_requested)
                    VALUES (:run_id, :tenant_id, :purpose, :graph_version, 'v1', :status, :current_node,
                            :state_payload, :transition_seq, 0, :cancel_requested)"""
                ),
                {
                    "run_id": state.run_id,
                    "tenant_id": state.tenant_id,
                    "purpose": state.purpose,
                    "graph_version": state.graph_version,
                    "status": state.status,
                    "current_node": state.current_node,
                    "state_payload": _json(state.model_dump(mode="json")),
                    "transition_seq": state.transition_count,
                    "cancel_requested": state.cancellation is not None,
                },
            )

    def acquire_lease(
        self,
        *,
        run_id: str,
        tenant_id: str,
        purpose: str,
        owner_id: str,
        lease_token: str,
        now: datetime | None = None,
    ) -> Lease:
        current = now or datetime.now(timezone.utc)
        expires = current + timedelta(seconds=self.lease_seconds)
        with self.engine.begin() as connection:
            lock = " FOR UPDATE" if connection.dialect.name == "postgresql" else ""
            run = (
                connection.execute(
                    text(
                        f"SELECT run_id, tenant_id, purpose, status, lease_fencing_seq "
                        f"FROM analytics_agent_runs WHERE run_id=:run_id{lock}"
                    ),
                    {"run_id": run_id},
                )
                .mappings()
                .first()
            )
            if run is None or run["tenant_id"] != tenant_id or run["purpose"] != purpose:
                raise ControlStoreError("run identity does not match tenant and purpose")
            if run["status"] == "terminal":
                raise LeaseUnavailable("terminal run cannot be leased")
            existing = (
                connection.execute(
                    text(
                        f"SELECT owner_id, lease_token, fencing_seq, expires_at "
                        f"FROM analytics_run_leases WHERE run_id=:run_id{lock}"
                    ),
                    {"run_id": run_id},
                )
                .mappings()
                .first()
            )
            if existing is not None and str(existing["expires_at"]) > _timestamp(current):
                raise LeaseUnavailable("run lease is held by a live worker")
            fencing = int(existing["fencing_seq"]) + 1 if existing is not None else 1
            params = {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "purpose": purpose,
                "owner_id": owner_id,
                "lease_token": lease_token,
                "fencing_seq": fencing,
                "expires_at": _timestamp(expires),
                "now": _timestamp(current),
            }
            if existing is None:
                connection.execute(
                    text("""INSERT INTO analytics_run_leases
                    (run_id, tenant_id, purpose, owner_id, lease_token, fencing_seq, expires_at, acquired_at, renewed_at)
                    VALUES (:run_id, :tenant_id, :purpose, :owner_id, :lease_token, :fencing_seq, :expires_at, :now, :now)"""),
                    params,
                )
            else:
                connection.execute(
                    text("""UPDATE analytics_run_leases SET owner_id=:owner_id, lease_token=:lease_token,
                    fencing_seq=:fencing_seq, expires_at=:expires_at, renewed_at=:now
                    WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose"""),
                    params,
                )
            connection.execute(
                text("UPDATE analytics_agent_runs SET lease_fencing_seq=:fencing_seq WHERE run_id=:run_id"),
                {"run_id": run_id, "fencing_seq": fencing},
            )
        return Lease(run_id, tenant_id, purpose, owner_id, lease_token, fencing, expires)

    def load_latest_checkpoint(self, *, run_id: str, tenant_id: str, purpose: str) -> AgentRunState:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("""SELECT state_payload FROM analytics_run_checkpoints
                WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose
                ORDER BY checkpoint_seq DESC LIMIT 1"""),
                {"run_id": run_id, "tenant_id": tenant_id, "purpose": purpose},
            ).first()
            if row is None:
                return self.load_run_state(run_id=run_id, tenant_id=tenant_id, purpose=purpose)
            return AgentRunState.model_validate(_payload(row[0]))

    def load_run_state(self, *, run_id: str, tenant_id: str, purpose: str) -> AgentRunState:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("""SELECT state_payload FROM analytics_agent_runs
                WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose"""),
                {"run_id": run_id, "tenant_id": tenant_id, "purpose": purpose},
            ).first()
            if row is None:
                raise ControlStoreError("run does not exist for tenant and purpose")
            return AgentRunState.model_validate(_payload(row[0]))

    def cancellation_requested(self, *, run_id: str, tenant_id: str, purpose: str) -> bool:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("""SELECT cancel_requested FROM analytics_agent_runs
                WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose"""),
                {"run_id": run_id, "tenant_id": tenant_id, "purpose": purpose},
            ).first()
            if row is None:
                raise ControlStoreError("run does not exist for tenant and purpose")
            return bool(row[0])

    def request_cancellation(
        self,
        *,
        run_id: str,
        tenant_id: str,
        purpose: str,
        cancellation: CancellationRequest,
    ) -> None:
        with self.engine.begin() as connection:
            lock = " FOR UPDATE" if connection.dialect.name == "postgresql" else ""
            row = connection.execute(
                text(
                    """SELECT state_payload, status FROM analytics_agent_runs
                WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose"""
                    + lock
                ),
                {"run_id": run_id, "tenant_id": tenant_id, "purpose": purpose},
            ).first()
            if row is None:
                raise ControlStoreError("run does not exist for tenant and purpose")
            if row[1] == "terminal":
                raise LeaseUnavailable("terminal run cannot be cancelled")
            state = AgentRunState.model_validate(_payload(row[0]))
            updated = state.model_copy(update={"status": "cancel_requested", "cancellation": cancellation})
            result = connection.execute(
                text("""UPDATE analytics_agent_runs SET status='cancel_requested', cancel_requested=true,
                state_payload=:state_payload, updated_at=:updated_at
                WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose AND status <> 'terminal'"""),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "purpose": purpose,
                    "state_payload": _json(updated.model_dump(mode="json")),
                    "updated_at": _timestamp(datetime.now(timezone.utc)),
                },
            )
            if result.rowcount != 1:
                raise StaleWorkerError("run became terminal while cancellation was requested")

    def release_lease(self, lease: Lease) -> None:
        with self.engine.begin() as connection:
            result = connection.execute(
                text("""DELETE FROM analytics_run_leases WHERE run_id=:run_id AND tenant_id=:tenant_id
                AND purpose=:purpose AND owner_id=:owner_id AND lease_token=:lease_token
                AND fencing_seq=:fencing_seq"""),
                {
                    "run_id": lease.run_id,
                    "tenant_id": lease.tenant_id,
                    "purpose": lease.purpose,
                    "owner_id": lease.owner_id,
                    "lease_token": lease.lease_token,
                    "fencing_seq": lease.fencing_seq,
                },
            )
            if result.rowcount != 1:
                raise StaleWorkerError("stale worker cannot release a newer lease")

    def create_review(self, review: DurableReviewDecision) -> None:
        if review.state != "pending" or review.resolved_at is not None:
            raise ControlStoreError("new review must be pending and unresolved")
        with self.engine.begin() as connection:
            existing = (
                connection.execute(
                    text("SELECT * FROM analytics_run_reviews WHERE review_id=:review_id"),
                    {"review_id": review.review_id},
                )
                .mappings()
                .first()
            )
            if existing is not None:
                current = _review_from_row(existing)
                if current == review:
                    return
                raise ControlStoreError("review ID already exists with different content")
            run = connection.execute(
                text("""SELECT status FROM analytics_agent_runs
                WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose"""),
                {"run_id": review.run_id, "tenant_id": review.tenant_id, "purpose": review.purpose},
            ).first()
            if run is None or run[0] == "terminal":
                raise ControlStoreError("review must reference an active scoped run")
            _insert_review(connection, review)

    def get_review(self, review_id: str, *, tenant_id: str, purpose: str) -> DurableReviewDecision:
        with self.engine.begin() as connection:
            lock = " FOR UPDATE" if connection.dialect.name == "postgresql" else ""
            row = (
                connection.execute(
                    text(
                        """SELECT * FROM analytics_run_reviews WHERE review_id=:review_id
                AND tenant_id=:tenant_id AND purpose=:purpose"""
                        + lock
                    ),
                    {"review_id": review_id, "tenant_id": tenant_id, "purpose": purpose},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ControlStoreError("review does not exist for tenant and purpose")
            review = _review_from_row(row)
            if review.state == "pending" and review.expires_at <= datetime.now(timezone.utc):
                connection.execute(
                    text(
                        "UPDATE analytics_run_reviews SET state='expired' WHERE review_id=:review_id AND state='pending'"
                    ),
                    {"review_id": review_id},
                )
                review = review.model_copy(update={"state": "expired"})
            return review

    def resolve_review(
        self,
        review_id: str,
        *,
        tenant_id: str,
        purpose: str,
        identity: AnalyticsIdentity,
        decision: str,
        plan_fingerprint: str,
        note: str | None = None,
        now: datetime | None = None,
    ) -> DurableReviewDecision:
        if identity.tenant_id != tenant_id or purpose not in identity.purposes:
            raise ControlStoreError("reviewer identity is not authorized for this tenant and purpose")
        reviewer_id = identity.user_id
        if decision not in {"approved", "rejected"}:
            raise ValueError("review decision must be approved or rejected")
        current = now or datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            lock = " FOR UPDATE" if connection.dialect.name == "postgresql" else ""
            row = (
                connection.execute(
                    text(
                        """SELECT * FROM analytics_run_reviews WHERE review_id=:review_id
                AND tenant_id=:tenant_id AND purpose=:purpose"""
                        + lock
                    ),
                    {"review_id": review_id, "tenant_id": tenant_id, "purpose": purpose},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ControlStoreError("review does not exist for tenant and purpose")
            review = _review_from_row(row)
            if review.state == "pending" and review.expires_at <= current:
                connection.execute(
                    text("UPDATE analytics_run_reviews SET state='expired' WHERE review_id=:review_id"),
                    {"review_id": review_id},
                )
                return review.model_copy(update={"state": "expired"})
            if review.state != "pending":
                raise StaleWorkerError("review is no longer pending")
            run = connection.execute(
                text(
                    """SELECT status, state_payload FROM analytics_agent_runs
                WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose"""
                    + lock
                ),
                {"run_id": review.run_id, "tenant_id": tenant_id, "purpose": purpose},
            ).first()
            if run is None or run[0] != "waiting_approval":
                raise StaleWorkerError("review is not attached to a paused active run")
            run_state = AgentRunState.model_validate(_payload(run[1]))
            approval = run_state.approval_state or {}
            if run_state.budget.deadline <= current:
                connection.execute(
                    text("UPDATE analytics_run_reviews SET state='expired' WHERE review_id=:review_id"),
                    {"review_id": review_id},
                )
                return review.model_copy(update={"state": "expired"})
            if (
                approval.get("review_id") != review.review_id
                or approval.get("plan_fingerprint") != review.plan_fingerprint
            ):
                raise StaleWorkerError("review no longer matches the paused run state")
            if reviewer_id == review.requested_by:
                raise ControlStoreError("requester cannot approve their own plan")
            if plan_fingerprint != review.plan_fingerprint:
                raise StaleWorkerError("approval plan fingerprint is stale")
            result = connection.execute(
                text("""UPDATE analytics_run_reviews SET state=:state, resolved_by=:reviewer_id,
                resolved_at=:resolved_at, resolution_note=:note
                WHERE review_id=:review_id AND state='pending'"""),
                {
                    "state": decision,
                    "reviewer_id": reviewer_id,
                    "resolved_at": current,
                    "note": note,
                    "review_id": review_id,
                },
            )
            if result.rowcount != 1:
                raise StaleWorkerError("review was resolved concurrently")
        return review.model_copy(
            update={
                "state": decision,
                "resolved_by": reviewer_id,
                "resolved_at": current,
                "resolution_note": note,
            }
        )

    def revise_review(
        self, previous_review_id: str, revised: DurableReviewDecision, *, identity: AnalyticsIdentity
    ) -> DurableReviewDecision:
        if (
            identity.tenant_id != revised.tenant_id
            or revised.purpose not in identity.purposes
            or revised.requested_by != identity.user_id
        ):
            raise ControlStoreError("review revision identity is not authorized")
        previous = self.get_review(
            previous_review_id,
            tenant_id=revised.tenant_id,
            purpose=revised.purpose,
        )
        if previous.state != "pending" or previous.requested_by != identity.user_id:
            raise StaleWorkerError("only the original requester can revise a pending review")
        if previous.run_id == revised.run_id or (previous.tenant_id, previous.purpose) != (
            revised.tenant_id,
            revised.purpose,
        ):
            raise ControlStoreError("an edited plan requires a new run in the same tenant and purpose")
        if revised.plan_fingerprint == previous.plan_fingerprint:
            raise ControlStoreError("revised review must bind to a changed plan fingerprint")
        revised = revised.model_copy(update={"revision": previous.revision + 1})
        with self.engine.begin() as connection:
            run = connection.execute(
                text("""SELECT status FROM analytics_agent_runs WHERE run_id=:run_id
                AND tenant_id=:tenant_id AND purpose=:purpose"""),
                {"run_id": revised.run_id, "tenant_id": revised.tenant_id, "purpose": revised.purpose},
            ).first()
            if run is None or run[0] == "terminal":
                raise ControlStoreError("edited review must reference a nonterminal replacement run")
            result = connection.execute(
                text("UPDATE analytics_run_reviews SET state='superseded' WHERE review_id=:id AND state='pending'"),
                {"id": previous_review_id},
            )
            if result.rowcount != 1:
                raise StaleWorkerError("review changed while being revised")
            _insert_review(connection, revised)
        return revised

    def replay_transitions(self, *, run_id: str, tenant_id: str, purpose: str) -> tuple[dict[str, Any], ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT transition_seq, graph_version, from_node, to_node, from_status,
                to_status, fencing_seq, idempotency_key, evidence_payload
                FROM analytics_run_transitions WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose
                ORDER BY transition_seq"""),
                    {"run_id": run_id, "tenant_id": tenant_id, "purpose": purpose},
                )
                .mappings()
                .all()
            )
        expected = 1
        replay: list[dict[str, Any]] = []
        for row in rows:
            if row["transition_seq"] != expected:
                raise ControlStoreError("transition history is not contiguous")
            replay.append(dict(row))
            expected += 1
        return tuple(replay)

    def commit_transition(self, state: AgentRunState, transition: Transition, *, fencing_seq: int) -> None:
        if transition.run_id != state.run_id or transition.tenant_id != state.tenant_id:
            raise ControlStoreError("transition identity does not match run state")
        if transition.graph_version != state.graph_version or transition.to_status != state.status:
            raise ControlStoreError("transition does not match the new run state")
        expected_seq = transition.sequence - 1
        with self.engine.begin() as connection:
            result = connection.execute(
                text("""UPDATE analytics_agent_runs
                SET current_node=:current_node, status=:status, state_payload=:state_payload,
                    transition_seq=:transition_seq, updated_at=:updated_at
                WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose
                  AND graph_version=:graph_version AND current_node=:from_node
                  AND status=:from_status AND transition_seq=:expected_seq
                  AND lease_fencing_seq=:fencing_seq AND status <> 'terminal'"""),
                {
                    "run_id": state.run_id,
                    "tenant_id": state.tenant_id,
                    "purpose": state.purpose,
                    "graph_version": state.graph_version,
                    "current_node": state.current_node,
                    "state_payload": _json(state.model_dump(mode="json")),
                    "transition_seq": transition.sequence,
                    "updated_at": _timestamp(datetime.now(timezone.utc)),
                    "status": state.status,
                    "from_node": transition.from_node,
                    "from_status": transition.from_status,
                    "expected_seq": expected_seq,
                    "fencing_seq": fencing_seq,
                },
            )
            if result.rowcount != 1:
                raise StaleWorkerError("stale worker cannot commit transition")
            connection.execute(
                text("""INSERT INTO analytics_run_transitions
                (run_id, transition_seq, tenant_id, purpose, graph_version, from_node, to_node,
                 from_status, to_status, fencing_seq, idempotency_key, evidence_payload)
                VALUES (:run_id, :sequence, :tenant_id, :purpose, :graph_version, :from_node, :to_node,
                        :from_status, :to_status, :fencing_seq, :idempotency_key, :evidence_payload)"""),
                {
                    "run_id": state.run_id,
                    "sequence": transition.sequence,
                    "tenant_id": state.tenant_id,
                    "purpose": state.purpose,
                    "graph_version": state.graph_version,
                    "from_node": transition.from_node,
                    "to_node": transition.to_node,
                    "from_status": transition.from_status,
                    "to_status": transition.to_status,
                    "fencing_seq": fencing_seq,
                    "idempotency_key": transition.idempotency_key,
                    "evidence_payload": _json([item.model_dump(mode="json") for item in transition.evidence]),
                },
            )
            connection.execute(
                text("""INSERT INTO analytics_run_checkpoints
                (run_id, checkpoint_seq, tenant_id, purpose, graph_version, state_version, current_node,
                 transition_seq, lease_fencing_seq, state_payload)
                VALUES (:run_id, :sequence, :tenant_id, :purpose, :graph_version, 'v1', :current_node,
                        :sequence, :fencing_seq, :state_payload)"""),
                {
                    "run_id": state.run_id,
                    "sequence": transition.sequence,
                    "tenant_id": state.tenant_id,
                    "purpose": state.purpose,
                    "graph_version": state.graph_version,
                    "current_node": state.current_node,
                    "fencing_seq": fencing_seq,
                    "state_payload": _json(state.model_dump(mode="json")),
                },
            )
            connection.execute(
                text("""INSERT INTO analytics_run_outbox
                (tenant_id, run_id, purpose, event_type, dedupe_key, payload)
                VALUES (:tenant_id, :run_id, :purpose, 'agent.transition', :dedupe_key, :payload)"""),
                {
                    "tenant_id": state.tenant_id,
                    "run_id": state.run_id,
                    "purpose": state.purpose,
                    "dedupe_key": f"{state.run_id}:{transition.sequence}",
                    "payload": _json({"run_id": state.run_id, "sequence": transition.sequence}),
                },
            )


def _insert_review(connection: Any, review: DurableReviewDecision) -> None:
    connection.execute(
        text("""INSERT INTO analytics_run_reviews
        (review_id, run_id, tenant_id, purpose, plan_fingerprint, requested_by,
         created_at, expires_at, state, resolved_by, resolved_at, resolution_note, revision)
        VALUES (:review_id, :run_id, :tenant_id, :purpose, :plan_fingerprint, :requested_by,
         :created_at, :expires_at, 'pending', NULL, NULL, NULL, :revision)"""),
        {
            "review_id": review.review_id,
            "run_id": review.run_id,
            "tenant_id": review.tenant_id,
            "purpose": review.purpose,
            "plan_fingerprint": review.plan_fingerprint,
            "requested_by": review.requested_by,
            "created_at": review.created_at,
            "expires_at": review.expires_at,
            "revision": review.revision,
        },
    )


def _review_from_row(row: Any) -> DurableReviewDecision:
    values = dict(row)
    for key in ("created_at", "expires_at", "resolved_at"):
        value = values.get(key)
        if isinstance(value, datetime) and value.tzinfo is None:
            values[key] = value.replace(tzinfo=timezone.utc)
    return DurableReviewDecision.model_validate(values)
