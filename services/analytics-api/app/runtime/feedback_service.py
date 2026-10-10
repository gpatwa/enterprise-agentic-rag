"""Capture structured feedback bound to a run's sealed evidence (ADS-050).

Recording feedback is the only effect. Nothing here writes to goldens, thresholds, policy, prompts,
the ontology, or the semantic contracts; later packets (ADS-051 onward) decide what, if anything,
a reviewer may do with it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.runtime.analyze_service import ServiceError
from app.runtime.control_store import ControlStoreError
from app.runtime.evidence_store import EvidenceNotFoundError, EvidenceStore
from app.runtime.feedback_store import FeedbackConflictError, FeedbackStore
from packages.platform_contracts.feedback import FeedbackReceipt, FeedbackRecord, FeedbackSubmission
from packages.platform_contracts.security import AnalyticsIdentity

_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_TARGET_COLLECTION = {
    "metric": "metrics",
    "dimension": "dimensions",
    "time_dimension": "dimensions",
    "filter_field": "fields",
}


class FeedbackService:
    def __init__(
        self,
        control_store: Any,
        evidence_store: EvidenceStore,
        store: FeedbackStore,
        contracts: Any,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.control, self.evidence, self.store, self.contracts, self.now = (
            control_store,
            evidence_store,
            store,
            contracts,
            now,
        )

    def submit(
        self, identity: AnalyticsIdentity, *, run_id: str, idempotency_key: str, submission: FeedbackSubmission
    ) -> tuple[FeedbackReceipt, FeedbackRecord]:
        if submission.purpose not in identity.purposes:
            raise ServiceError(403, "purpose_not_authorized")
        if not _KEY.match(idempotency_key or ""):
            raise ServiceError(400, "invalid_idempotency_key")
        try:
            state = self.control.load_latest_checkpoint(
                run_id=run_id, tenant_id=identity.tenant_id, purpose=submission.purpose
            )
        except ControlStoreError as exc:
            raise ServiceError(404, "run_not_found") from exc
        if state.status != "terminal":
            raise ServiceError(409, "run_not_terminal")
        try:
            envelope = self.evidence.get(run_id, tenant_id=identity.tenant_id, purpose=submission.purpose)
        except EvidenceNotFoundError as exc:
            raise ServiceError(409, "evidence_unavailable") from exc
        if submission.correction is not None:
            self._check_correction(envelope.semantic_contract, submission)
        record = FeedbackRecord(
            feedback_id=hashlib.sha256(
                f"{identity.tenant_id}:{run_id}:{identity.user_id}:{idempotency_key}".encode()
            ).hexdigest()[:32],
            tenant_id=identity.tenant_id,
            run_id=run_id,
            purpose=submission.purpose,
            submitted_by=identity.user_id,
            idempotency_key=idempotency_key,
            verdict=submission.verdict,
            reason_code=submission.reason_code,
            correction=submission.correction,
            note=submission.note,
            terminal_kind=envelope.terminal_kind,
            evidence_fingerprint=envelope.content_fingerprint,
            result_fingerprint=envelope.result.result_fingerprint if envelope.result else None,
            intent_fingerprint=envelope.intent_fingerprint,
            semantic_contract=envelope.semantic_contract,
            context_snapshot_id=envelope.context_snapshot_id,
            submission_fingerprint=hashlib.sha256(submission.model_dump_json(exclude_none=True).encode()).hexdigest(),
            created_at=self.now(),
        )
        try:
            appended = self.store.append(record)
        except FeedbackConflictError as exc:
            raise ServiceError(409, "idempotency_key_reused") from exc
        stored = appended.record
        return (
            FeedbackReceipt(
                feedback_id=stored.feedback_id,
                run_id=stored.run_id,
                evidence_fingerprint=stored.evidence_fingerprint,
                created=appended.created,
            ),
            stored,
        )

    def _check_correction(self, contract_ref: str | None, submission: FeedbackSubmission) -> None:
        if not contract_ref or "@" not in contract_ref:
            raise ServiceError(422, "correction_unverifiable")
        contract_id, version = contract_ref.rsplit("@", 1)
        try:
            contract = self.contracts.get_certified(contract_id, version).contract
        except LookupError as exc:
            raise ServiceError(422, "correction_unverifiable") from exc
        correction = submission.correction
        known = {item.id for item in getattr(contract, _TARGET_COLLECTION[correction.target])}
        if correction.semantic_id not in known:
            raise ServiceError(422, "unknown_semantic_id")
