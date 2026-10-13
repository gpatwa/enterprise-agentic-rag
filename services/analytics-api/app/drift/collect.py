"""Read-only extraction of drift observations from terminal runs (ADS-058)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Engine, text

from packages.platform_contracts.agent_runtime import AgentRunState
from packages.platform_contracts.drift import RunObservation

ContextAge = Callable[[str, datetime], "float | None"]


def _moment(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace(" ", "T"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def observation_from_state(
    state: AgentRunState, *, created_at: datetime, completed_at: datetime, context_age_hours: float | None = None
) -> RunObservation:
    """Numbers and codes only: no request text, rows, SQL, or reasons."""
    cost = (state.cost_decision or {}).get("observed_cost_units")
    return RunObservation(
        run_id=state.run_id,
        tenant_id=state.tenant_id,
        observed_at=completed_at,
        outcome=state.terminal_outcome.kind if state.terminal_outcome else "failed",
        error_codes=tuple(sorted({error.code for error in state.errors})),
        context_items=len(state.context_pack.items) if state.context_pack else None,
        context_age_hours=context_age_hours,
        latency_ms=max(0.0, (completed_at - created_at).total_seconds() * 1000),
        cost_units=float(cost) if cost is not None else None,
    )


def collect_observations(
    engine: Engine,
    tenant_id: str,
    *,
    since: datetime,
    until: datetime,
    context_age: ContextAge | None = None,
) -> tuple[RunObservation, ...]:
    """Terminal runs of one tenant that finished in [since, until); the store is only read."""
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """SELECT state_payload, created_at, updated_at FROM analytics_agent_runs
                    WHERE tenant_id=:tenant_id AND status='terminal' ORDER BY updated_at, run_id"""
                ),
                {"tenant_id": tenant_id},
            )
            .mappings()
            .all()
        )
    observations = []
    for row in rows:
        completed = _moment(row["updated_at"])
        if not since <= completed < until:
            continue
        payload = row["state_payload"]
        state = AgentRunState.model_validate(json.loads(payload) if isinstance(payload, str) else payload)
        age = context_age(state.context_snapshot_id, completed) if context_age else None
        observations.append(
            observation_from_state(
                state, created_at=_moment(row["created_at"]), completed_at=completed, context_age_hours=age
            )
        )
    return tuple(observations)
