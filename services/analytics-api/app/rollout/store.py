"""Append-only rollout, event, and release-pointer persistence (ADS-057)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from packages.platform_contracts.rollout import ReleasePointer, RolloutEvent, RolloutRecord


class RolloutStoreError(RuntimeError):
    pass


class RolloutStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create(self, record: RolloutRecord) -> bool:
        """Insert the rollout; False if this exact rollout already exists."""
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text("""INSERT INTO analytics_rollouts (tenant_id, rollout_id, subject_id, subject_fingerprint, payload)
                    VALUES (:t, :r, :s, :f, :p)"""),
                    {
                        "t": record.tenant_id,
                        "r": record.rollout_id,
                        "s": record.subject_id,
                        "f": record.subject_fingerprint,
                        "p": json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                    },
                )
            return True
        except IntegrityError:
            return False

    def get(self, rollout_id: str, *, tenant_id: str) -> RolloutRecord:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT payload FROM analytics_rollouts WHERE tenant_id=:t AND rollout_id=:r"),
                    {"t": tenant_id, "r": rollout_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise RolloutStoreError("no such rollout in this tenant")
        return RolloutRecord.model_validate(_load(row["payload"]))

    def events(self, rollout_id: str, *, tenant_id: str) -> tuple[RolloutEvent, ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT seq, event_type, actor, detail, event_at FROM analytics_rollout_events
                    WHERE tenant_id=:t AND rollout_id=:r ORDER BY seq"""),
                    {"t": tenant_id, "r": rollout_id},
                )
                .mappings()
                .all()
            )
        return tuple(
            RolloutEvent(
                seq=r["seq"],
                event_type=r["event_type"],
                actor=r["actor"],
                detail=_load(r["detail"]),
                created_at=_aware(r["event_at"]),
            )
            for r in rows
        )

    def append_event(
        self, tenant_id: str, rollout_id: str, event_type: str, actor: str, detail: dict, at: datetime
    ) -> None:
        for _ in range(3):
            try:
                with self.engine.begin() as connection:
                    seq = (
                        connection.execute(
                            text(
                                "SELECT COALESCE(MAX(seq), 0) FROM analytics_rollout_events WHERE tenant_id=:t AND rollout_id=:r"
                            ),
                            {"t": tenant_id, "r": rollout_id},
                        ).scalar()
                        + 1
                    )
                    connection.execute(
                        text("""INSERT INTO analytics_rollout_events (tenant_id, rollout_id, seq, event_type, actor, detail, event_at)
                        VALUES (:t, :r, :s, :e, :a, :d, :at)"""),
                        {
                            "t": tenant_id,
                            "r": rollout_id,
                            "s": seq,
                            "e": event_type,
                            "a": actor,
                            "d": json.dumps(detail, sort_keys=True),
                            "at": at,
                        },
                    )
                return
            except IntegrityError:
                continue
        raise RolloutStoreError("could not append the rollout event after repeated contention")

    def append_pointer(self, prompt_name: str, version: str, rollout_id: str | None, reason: str, at: datetime) -> None:
        for _ in range(3):
            try:
                with self.engine.begin() as connection:
                    seq = (
                        connection.execute(
                            text("SELECT COALESCE(MAX(seq), 0) FROM analytics_release_pointer WHERE prompt_name=:n"),
                            {"n": prompt_name},
                        ).scalar()
                        + 1
                    )
                    connection.execute(
                        text("""INSERT INTO analytics_release_pointer (prompt_name, seq, version, rollout_id, reason, set_at)
                        VALUES (:n, :s, :v, :r, :why, :at)"""),
                        {"n": prompt_name, "s": seq, "v": version, "r": rollout_id, "why": reason, "at": at},
                    )
                return
            except IntegrityError:
                continue
        raise RolloutStoreError("could not append the release pointer after repeated contention")

    def pointer_history(self, prompt_name: str) -> tuple[ReleasePointer, ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT seq, version, rollout_id, reason, set_at FROM analytics_release_pointer WHERE prompt_name=:n ORDER BY seq"
                    ),
                    {"n": prompt_name},
                )
                .mappings()
                .all()
            )
        return tuple(
            ReleasePointer(
                prompt_name=prompt_name,
                seq=r["seq"],
                version=r["version"],
                rollout_id=r["rollout_id"],
                reason=r["reason"],
                set_at=_aware(r["set_at"]),
            )
            for r in rows
        )

    def active_version(self, prompt_name: str) -> str | None:
        history = self.pointer_history(prompt_name)
        return history[-1].version if history else None


def _load(payload: Any) -> Any:
    return json.loads(payload) if isinstance(payload, str) else payload


def _aware(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
