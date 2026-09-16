"""Transactional primitives for the bounded analytics agent control store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, text

from packages.platform_contracts.agent_runtime import AgentRunState, Transition


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
            run = connection.execute(
                text(
                    f"SELECT run_id, tenant_id, purpose, status, lease_fencing_seq "
                    f"FROM analytics_agent_runs WHERE run_id=:run_id{lock}"
                ),
                {"run_id": run_id},
            ).mappings().first()
            if run is None or run["tenant_id"] != tenant_id or run["purpose"] != purpose:
                raise ControlStoreError("run identity does not match tenant and purpose")
            if run["status"] == "terminal":
                raise LeaseUnavailable("terminal run cannot be leased")
            existing = connection.execute(
                text(
                    f"SELECT owner_id, lease_token, fencing_seq, expires_at "
                    f"FROM analytics_run_leases WHERE run_id=:run_id{lock}"
                ),
                {"run_id": run_id},
            ).mappings().first()
            if existing is not None and str(existing["expires_at"]) > _timestamp(current):
                raise LeaseUnavailable("run lease is held by a live worker")
            fencing = int(existing["fencing_seq"]) + 1 if existing is not None else 1
            params = {
                "run_id": run_id, "tenant_id": tenant_id, "purpose": purpose,
                "owner_id": owner_id, "lease_token": lease_token, "fencing_seq": fencing,
                "expires_at": _timestamp(expires), "now": _timestamp(current),
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
                raise ControlStoreError("no checkpoint exists for run identity")
            return AgentRunState.model_validate(_payload(row[0]))

    def replay_transitions(self, *, run_id: str, tenant_id: str, purpose: str) -> tuple[dict[str, Any], ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("""SELECT transition_seq, graph_version, from_node, to_node, from_status,
                to_status, fencing_seq, idempotency_key, evidence_payload
                FROM analytics_run_transitions WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose
                ORDER BY transition_seq"""),
                {"run_id": run_id, "tenant_id": tenant_id, "purpose": purpose},
            ).mappings().all()
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
                    "run_id": state.run_id, "tenant_id": state.tenant_id, "purpose": state.purpose,
                    "graph_version": state.graph_version, "current_node": state.current_node,
                    "state_payload": _json(state.model_dump(mode="json")),
                    "transition_seq": transition.sequence, "updated_at": _timestamp(datetime.now(timezone.utc)),
                    "status": state.status,
                    "from_node": transition.from_node, "from_status": transition.from_status,
                    "expected_seq": expected_seq, "fencing_seq": fencing_seq,
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
                    "run_id": state.run_id, "sequence": transition.sequence, "tenant_id": state.tenant_id,
                    "purpose": state.purpose, "graph_version": state.graph_version,
                    "from_node": transition.from_node, "to_node": transition.to_node,
                    "from_status": transition.from_status, "to_status": transition.to_status,
                    "fencing_seq": fencing_seq, "idempotency_key": transition.idempotency_key,
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
                    "run_id": state.run_id, "sequence": transition.sequence, "tenant_id": state.tenant_id,
                    "purpose": state.purpose, "graph_version": state.graph_version,
                    "current_node": state.current_node, "fencing_seq": fencing_seq,
                    "state_payload": _json(state.model_dump(mode="json")),
                },
            )
            connection.execute(
                text("""INSERT INTO analytics_run_outbox
                (tenant_id, run_id, purpose, event_type, dedupe_key, payload)
                VALUES (:tenant_id, :run_id, :purpose, 'agent.transition', :dedupe_key, :payload)"""),
                {
                    "tenant_id": state.tenant_id, "run_id": state.run_id, "purpose": state.purpose,
                    "dedupe_key": f"{state.run_id}:{transition.sequence}",
                    "payload": _json({"run_id": state.run_id, "sequence": transition.sequence}),
                },
            )
