"""Append-only, tenant-scoped feedback persistence (ADS-050)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from packages.platform_contracts.feedback import FeedbackRecord


class FeedbackStoreError(RuntimeError):
    pass


class FeedbackConflictError(FeedbackStoreError):
    """The idempotency key was already used for a different submission."""


class FeedbackNotFoundError(FeedbackStoreError):
    pass


@dataclass(frozen=True)
class AppendedFeedback:
    record: FeedbackRecord
    created: bool


class FeedbackStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, record: FeedbackRecord) -> AppendedFeedback:
        """Idempotent per (tenant, run, submitter, key): same submission returns the first record."""
        for _ in range(2):
            try:
                with self.engine.begin() as connection:
                    existing = self._find(connection, record)
                    if existing is not None:
                        if existing.submission_fingerprint != record.submission_fingerprint:
                            raise FeedbackConflictError("this idempotency key was used for different feedback")
                        return AppendedFeedback(existing, created=False)
                    connection.execute(
                        text("""INSERT INTO analytics_feedback
                        (tenant_id, feedback_id, run_id, purpose, submitted_by, idempotency_key,
                         submission_fingerprint, verdict, reason_code, payload)
                        VALUES (:tenant_id, :feedback_id, :run_id, :purpose, :submitted_by, :idempotency_key,
                                :submission_fingerprint, :verdict, :reason_code, :payload)"""),
                        {
                            "tenant_id": record.tenant_id,
                            "feedback_id": record.feedback_id,
                            "run_id": record.run_id,
                            "purpose": record.purpose,
                            "submitted_by": record.submitted_by,
                            "idempotency_key": record.idempotency_key,
                            "submission_fingerprint": record.submission_fingerprint,
                            "verdict": record.verdict,
                            "reason_code": record.reason_code,
                            "payload": json.dumps(
                                record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                            ),
                        },
                    )
                    return AppendedFeedback(record, created=True)
            except IntegrityError:
                continue  # a concurrent identical submission won the race; re-read it
        raise FeedbackStoreError("could not append feedback after repeated contention")

    def get(self, feedback_id: str, *, tenant_id: str) -> FeedbackRecord:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT payload FROM analytics_feedback WHERE tenant_id=:t AND feedback_id=:f"),
                    {"t": tenant_id, "f": feedback_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise FeedbackNotFoundError("no such feedback in this tenant")
        return FeedbackRecord.model_validate(_load(row["payload"]))

    def for_run(self, run_id: str, *, tenant_id: str) -> tuple[FeedbackRecord, ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT payload FROM analytics_feedback
                    WHERE tenant_id=:t AND run_id=:r ORDER BY created_at, feedback_id"""),
                    {"t": tenant_id, "r": run_id},
                )
                .mappings()
                .all()
            )
        return tuple(FeedbackRecord.model_validate(_load(row["payload"])) for row in rows)

    @staticmethod
    def _find(connection: Any, record: FeedbackRecord) -> FeedbackRecord | None:
        row = (
            connection.execute(
                text("""SELECT payload FROM analytics_feedback WHERE tenant_id=:t AND run_id=:r
                AND submitted_by=:u AND idempotency_key=:k"""),
                {"t": record.tenant_id, "r": record.run_id, "u": record.submitted_by, "k": record.idempotency_key},
            )
            .mappings()
            .first()
        )
        return FeedbackRecord.model_validate(_load(row["payload"])) if row else None


def _load(payload: Any) -> Any:
    return json.loads(payload) if isinstance(payload, str) else payload
