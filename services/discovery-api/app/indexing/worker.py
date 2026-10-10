"""Bounded outbox indexing over a provider-neutral bulk contract."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BulkIndexRequest(_Model):
    """One versioned outbox record ready for an idempotent upsert."""

    checkpoint: int = Field(ge=1)
    tenant_id: str = Field(min_length=1, max_length=255)
    document_id: str = Field(min_length=1, max_length=255)
    document: dict[str, Any]
    document_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_document_identity(self) -> "BulkIndexRequest":
        if not self.tenant_id.strip() or not self.document_id.strip():
            raise ValueError("tenant_id and document_id must be non-blank")
        if self.document.get("tenant_id") != self.tenant_id:
            raise ValueError("document tenant does not match request tenant")
        if self.document.get("exposure_key") != self.document_id:
            raise ValueError("document_id must match the stable exposure_key")
        return self


class BulkIndexResult(_Model):
    """Provider response for one bounded bulk attempt."""

    accepted_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    failed_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)
    transient_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000)

    @model_validator(mode="after")
    def validate_partitions(self) -> "BulkIndexResult":
        groups = (set(self.accepted_ids), set(self.failed_ids), set(self.transient_ids))
        if any(not item.strip() for group in groups for item in group):
            raise ValueError("provider IDs must be non-blank")
        if sum(map(len, groups)) != len(set().union(*groups)):
            raise ValueError("provider result partitions must be disjoint")
        return self


class PoisonRecord(_Model):
    """Redacted quarantine evidence for a record that exhausted retries."""

    checkpoint: int = Field(ge=1)
    document_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=128)
    attempts: int = Field(ge=1, le=32)


class IndexingEvidence(_Model):
    """Bounded, redacted result of one worker run."""

    received: int = Field(ge=0, le=10_000)
    accepted: int = Field(ge=0, le=10_000)
    quarantined: int = Field(ge=0, le=10_000)
    attempts: int = Field(ge=0, le=320_000)
    checkpoint: int = Field(ge=0)
    failures: tuple[PoisonRecord, ...] = Field(default_factory=tuple, max_length=10_000)
    external_index_updated: bool = False


class BulkIndexProvider(Protocol):
    """Minimal provider boundary; implementations own external I/O."""

    def bulk_upsert(self, requests: tuple[BulkIndexRequest, ...]) -> BulkIndexResult:
        """Upsert a bounded batch and partition accepted/transient/failed IDs."""


class FakeBulkIndexProvider:
    """Deterministic in-memory provider for worker tests only."""

    def __init__(
        self,
        *,
        transient_attempts: Mapping[str, int] | None = None,
        permanent_failures: Iterable[str] = (),
    ) -> None:
        self._transient_attempts = dict(transient_attempts or {})
        self._permanent_failures = frozenset(permanent_failures)
        self._attempts: dict[str, int] = {}
        self._documents: dict[str, dict[str, Any]] = {}

    @property
    def documents(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self._documents.items()}

    @property
    def attempts(self) -> dict[str, int]:
        return dict(self._attempts)

    def bulk_upsert(self, requests: tuple[BulkIndexRequest, ...]) -> BulkIndexResult:
        accepted: list[str] = []
        failed: list[str] = []
        transient: list[str] = []
        for request in requests:
            document_id = request.document_id
            attempt = self._attempts.get(document_id, 0) + 1
            self._attempts[document_id] = attempt
            if document_id in self._permanent_failures:
                failed.append(document_id)
            elif attempt <= self._transient_attempts.get(document_id, 0):
                transient.append(document_id)
            else:
                self._documents[document_id] = dict(request.document)
                accepted.append(document_id)
        return BulkIndexResult(
            accepted_ids=tuple(accepted), failed_ids=tuple(failed), transient_ids=tuple(transient)
        )


class IndexingWorker:
    """Process an outbox slice with bounded attempts and explicit quarantine."""

    def __init__(
        self,
        provider: BulkIndexProvider,
        *,
        batch_size: int = 50,
        max_attempts: int = 3,
        base_backoff_seconds: float = 0.0,
        max_backoff_seconds: float = 1.0,
    ) -> None:
        if not 1 <= batch_size <= 1_000:
            raise ValueError("batch_size must be between 1 and 1000")
        if not 1 <= max_attempts <= 8:
            raise ValueError("max_attempts must be between 1 and 8")
        if not 0 <= base_backoff_seconds <= 1:
            raise ValueError("base_backoff_seconds must be between 0 and 1")
        if not 0 <= max_backoff_seconds <= 30 or base_backoff_seconds > max_backoff_seconds:
            raise ValueError("backoff bounds are invalid")
        self.provider = provider
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds

    def run(self, records: Iterable[BulkIndexRequest], *, checkpoint: int = 0) -> IndexingEvidence:
        ordered = tuple(records)
        if len(ordered) > 10_000:
            raise ValueError("worker input exceeds the bounded run limit")
        if any(record.checkpoint <= checkpoint for record in ordered):
            raise ValueError("records must be after the supplied checkpoint")
        if tuple(sorted(ordered, key=lambda record: record.checkpoint)) != ordered:
            raise ValueError("records must be ordered by checkpoint")
        if len({record.checkpoint for record in ordered}) != len(ordered):
            raise ValueError("record checkpoints must be unique")
        if len({record.document_id for record in ordered}) != len(ordered):
            raise ValueError("document IDs must be unique within a run")

        accepted_ids: set[str] = set()
        failures: list[PoisonRecord] = []
        attempts_total = 0
        for start in range(0, len(ordered), self.batch_size):
            batch = ordered[start : start + self.batch_size]
            pending = {record.document_id: record for record in batch}
            for attempt in range(1, self.max_attempts + 1):
                if not pending:
                    break
                result = self.provider.bulk_upsert(tuple(pending.values()))
                attempts_total += len(pending)
                current_ids = set(pending)
                accepted = current_ids & set(result.accepted_ids)
                failed_ids = current_ids & set(result.failed_ids)
                transient_ids = current_ids & set(result.transient_ids)
                unknown_ids = current_ids - accepted - failed_ids - transient_ids
                if unknown_ids:
                    raise RuntimeError("provider returned an incomplete bulk result")
                accepted_ids.update(accepted)
                for document_id in failed_ids:
                    record = next((item for item in batch if item.document_id == document_id), None)
                    if record is not None:
                        failures.append(self._poison(record, "provider_rejected", attempt))
                pending = {key: pending[key] for key in transient_ids}
                if pending and attempt < self.max_attempts:
                    time.sleep(min(self.max_backoff_seconds, self.base_backoff_seconds * 2 ** (attempt - 1)))
            for record in pending.values():
                failures.append(self._poison(record, "retry_exhausted", self.max_attempts))

        failed_checkpoints = {failure.checkpoint for failure in failures}
        new_checkpoint = checkpoint
        for record in ordered:
            if record.checkpoint in failed_checkpoints or record.document_id not in accepted_ids:
                break
            new_checkpoint = record.checkpoint
        return IndexingEvidence(
            received=len(ordered),
            accepted=len(accepted_ids),
            quarantined=len(failures),
            attempts=attempts_total,
            checkpoint=new_checkpoint,
            failures=tuple(failures),
        )

    @staticmethod
    def _poison(record: BulkIndexRequest, reason: str, attempts: int) -> PoisonRecord:
        digest = hashlib.sha256(record.document_id.encode("utf-8")).hexdigest()
        return PoisonRecord(
            checkpoint=record.checkpoint,
            document_digest=digest,
            reason=reason,
            attempts=attempts,
        )
