"""Append-only review and event persistence (ADS-055)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from packages.platform_contracts.review import ReviewEvent, ReviewRecord


class ReviewStoreError(RuntimeError):
    pass


class ReviewStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create(self, record: ReviewRecord) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO analytics_reviews
                (tenant_id, review_id, purpose, subject_kind, subject_id, subject_fingerprint, requested_by, payload)
                VALUES (:t, :r, :p, :k, :s, :f, :u, :payload)"""),
                {
                    "t": record.tenant_id,
                    "r": record.review_id,
                    "p": record.purpose,
                    "k": record.subject.kind,
                    "s": record.subject.subject_id,
                    "f": record.subject.content_fingerprint,
                    "u": record.requested_by,
                    "payload": json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                },
            )

    def get(self, review_id: str, *, tenant_id: str) -> ReviewRecord:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT payload FROM analytics_reviews WHERE tenant_id=:t AND review_id=:r"),
                    {"t": tenant_id, "r": review_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise ReviewStoreError("no such review in this tenant")
        return ReviewRecord.model_validate(_load(row["payload"]))

    def for_subject(self, kind: str, subject_id: str, fingerprint: str, *, tenant_id: str) -> tuple[ReviewRecord, ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT payload FROM analytics_reviews WHERE tenant_id=:t AND subject_kind=:k
                    AND subject_id=:s AND subject_fingerprint=:f ORDER BY created_at, review_id"""),
                    {"t": tenant_id, "k": kind, "s": subject_id, "f": fingerprint},
                )
                .mappings()
                .all()
            )
        return tuple(ReviewRecord.model_validate(_load(row["payload"])) for row in rows)

    def pending_candidates(self, *, tenant_id: str) -> tuple[ReviewRecord, ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("SELECT payload FROM analytics_reviews WHERE tenant_id=:t ORDER BY created_at, review_id"),
                    {"t": tenant_id},
                )
                .mappings()
                .all()
            )
        return tuple(ReviewRecord.model_validate(_load(row["payload"])) for row in rows)

    def events(self, review_id: str, *, tenant_id: str) -> tuple[ReviewEvent, ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT seq, event_type, actor, note, event_at FROM analytics_review_events
                    WHERE tenant_id=:t AND review_id=:r ORDER BY seq"""),
                    {"t": tenant_id, "r": review_id},
                )
                .mappings()
                .all()
            )
        return tuple(
            ReviewEvent(
                seq=r["seq"],
                event_type=r["event_type"],
                actor=r["actor"],
                note=r["note"],
                created_at=_aware(r["event_at"]),
            )
            for r in rows
        )

    def append_event(
        self, tenant_id: str, review_id: str, event_type: str, actor: str, note: str | None, at: datetime
    ) -> ReviewEvent:
        for _ in range(3):
            try:
                with self.engine.begin() as connection:
                    seq = (
                        connection.execute(
                            text(
                                "SELECT COALESCE(MAX(seq), 0) FROM analytics_review_events WHERE tenant_id=:t AND review_id=:r"
                            ),
                            {"t": tenant_id, "r": review_id},
                        ).scalar()
                        + 1
                    )
                    connection.execute(
                        text("""INSERT INTO analytics_review_events (tenant_id, review_id, seq, event_type, actor, note, event_at)
                        VALUES (:t, :r, :s, :e, :a, :n, :at)"""),
                        {"t": tenant_id, "r": review_id, "s": seq, "e": event_type, "a": actor, "n": note, "at": at},
                    )
                return ReviewEvent(seq=seq, event_type=event_type, actor=actor, note=note, created_at=at)  # type: ignore[arg-type]
            except IntegrityError:
                continue  # another writer took this sequence number; recompute
        raise ReviewStoreError("could not append the review event after repeated contention")


def _load(payload: Any) -> Any:
    return json.loads(payload) if isinstance(payload, str) else payload


def _aware(value: datetime | str) -> datetime:
    from datetime import timezone

    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
