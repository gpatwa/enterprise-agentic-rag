"""Triage service and append-only store (ADS-051). On demand only: nothing calls it automatically."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.runtime.control_store import ControlStoreError
from app.runtime.evidence_store import EvidenceNotFoundError, EvidenceStore
from app.runtime.feedback_store import FeedbackNotFoundError, FeedbackStore
from app.triage.rules import TriageInputs, triage_decision
from packages.platform_contracts.triage import TRIAGE_RULES_VERSION, TriageRecord, decision_fingerprint


class TriageError(RuntimeError):
    """The feedback cannot be triaged; the message names the missing input, never run content."""


class TriageConflictError(TriageError):
    """The same rules version produced a different decision for this feedback."""


class TriageStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, record: TriageRecord) -> tuple[TriageRecord, bool]:
        for _ in range(2):
            try:
                with self.engine.begin() as connection:
                    existing = self._find(connection, record.tenant_id, record.feedback_id, record.rules_version)
                    if existing is not None:
                        if existing.decision_fingerprint != record.decision_fingerprint:
                            raise TriageConflictError("this rules version already triaged this feedback differently")
                        return existing, False
                    connection.execute(
                        text("""INSERT INTO analytics_feedback_triage
                        (tenant_id, triage_id, feedback_id, rules_version, category, rule_id,
                         decision_fingerprint, payload)
                        VALUES (:tenant_id, :triage_id, :feedback_id, :rules_version, :category, :rule_id,
                                :decision_fingerprint, :payload)"""),
                        {
                            "tenant_id": record.tenant_id,
                            "triage_id": record.triage_id,
                            "feedback_id": record.feedback_id,
                            "rules_version": record.rules_version,
                            "category": record.category,
                            "rule_id": record.rule_id,
                            "decision_fingerprint": record.decision_fingerprint,
                            "payload": json.dumps(
                                record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                            ),
                        },
                    )
                    return record, True
            except IntegrityError:
                continue
        raise TriageError("could not append triage after repeated contention")

    def get(self, triage_id: str, *, tenant_id: str) -> TriageRecord:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT payload FROM analytics_feedback_triage WHERE tenant_id=:t AND triage_id=:i"),
                    {"t": tenant_id, "i": triage_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise TriageError("no such triage record in this tenant")
        return TriageRecord.model_validate(_load(row["payload"]))

    def for_feedback(self, feedback_id: str, *, tenant_id: str) -> tuple[TriageRecord, ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT payload FROM analytics_feedback_triage
                    WHERE tenant_id=:t AND feedback_id=:f ORDER BY created_at, triage_id"""),
                    {"t": tenant_id, "f": feedback_id},
                )
                .mappings()
                .all()
            )
        return tuple(TriageRecord.model_validate(_load(row["payload"])) for row in rows)

    @staticmethod
    def _find(connection: Any, tenant_id: str, feedback_id: str, rules_version: str) -> TriageRecord | None:
        row = (
            connection.execute(
                text("""SELECT payload FROM analytics_feedback_triage
                WHERE tenant_id=:t AND feedback_id=:f AND rules_version=:v"""),
                {"t": tenant_id, "f": feedback_id, "v": rules_version},
            )
            .mappings()
            .first()
        )
        return TriageRecord.model_validate(_load(row["payload"])) if row else None


class TriageService:
    def __init__(
        self,
        control_store: Any,
        evidence_store: EvidenceStore,
        feedback_store: FeedbackStore,
        store: TriageStore,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.control, self.evidence, self.feedback, self.store, self.now = (
            control_store,
            evidence_store,
            feedback_store,
            store,
            now,
        )

    def triage(self, feedback_id: str, *, tenant_id: str) -> TriageRecord:
        """Classify one feedback record. Idempotent per rules version; never modifies anything else."""
        try:
            feedback = self.feedback.get(feedback_id, tenant_id=tenant_id)
            envelope = self.evidence.get(feedback.run_id, tenant_id=tenant_id, purpose=feedback.purpose)
            state = self.control.load_latest_checkpoint(
                run_id=feedback.run_id, tenant_id=tenant_id, purpose=feedback.purpose
            )
        except (FeedbackNotFoundError, EvidenceNotFoundError, ControlStoreError) as exc:
            raise TriageError("feedback, evidence, or run is not available for triage") from exc
        intent = state.intent or {}
        used = {m["metric_id"] for m in intent.get("metrics", [])}
        used |= {g["dimension_id"] for g in intent.get("group_by", [])}
        used |= {f["field_id"] for f in intent.get("filters", [])}
        if intent.get("time_range"):
            used.add(intent["time_range"]["dimension_id"])
        pack = state.context_pack
        context_ids = (
            {item.asset_id for item in pack.items}
            | {edge.from_node_id for edge in pack.graph_closure}
            | {edge.to_node_id for edge in pack.graph_closure}
            if pack
            else set()
        )
        inputs = TriageInputs(
            verdict=feedback.verdict,
            reason_code=feedback.reason_code,
            correction_target=feedback.correction.target if feedback.correction else None,
            correction_id=feedback.correction.semantic_id if feedback.correction else None,
            terminal_kind=envelope.terminal_kind,
            error_codes=tuple(e.code for e in envelope.errors),
            error_references=tuple(e.reference for e in envelope.errors),
            validation_status=envelope.result.validation_status if envelope.result else None,
            validation_issue_codes=envelope.result.issue_codes if envelope.result else (),
            policy_effect=envelope.policy.effect if envelope.policy else None,
            used_ids=frozenset(used),
            context_ids=frozenset(context_ids),
            omitted_ids=frozenset(pack.omitted_asset_ids) - context_ids if pack else frozenset(),
        )
        decision = triage_decision(inputs)
        fingerprint = decision_fingerprint(
            rules_version=TRIAGE_RULES_VERSION,
            category=decision.category,
            rule_id=decision.rule_id,
            basis_kind=decision.basis_kind,
            evidence_basis=decision.evidence_basis,
            alternates=decision.alternates,
            conflict=decision.conflict,
        )
        record = TriageRecord(
            triage_id=hashlib.sha256(f"{tenant_id}:{feedback_id}:{TRIAGE_RULES_VERSION}".encode()).hexdigest()[:32],
            tenant_id=tenant_id,
            feedback_id=feedback_id,
            run_id=feedback.run_id,
            purpose=feedback.purpose,
            rules_version=TRIAGE_RULES_VERSION,
            category=decision.category,
            rule_id=decision.rule_id,
            basis_kind=decision.basis_kind,
            evidence_basis=decision.evidence_basis,
            alternates=decision.alternates,
            conflict=decision.conflict,
            evidence_fingerprint=feedback.evidence_fingerprint,
            feedback_fingerprint=feedback.submission_fingerprint,
            decision_fingerprint=fingerprint,
            triaged_at=self.now(),
        )
        return self.store.append(record)[0]


def _load(payload: Any) -> Any:
    return json.loads(payload) if isinstance(payload, str) else payload
