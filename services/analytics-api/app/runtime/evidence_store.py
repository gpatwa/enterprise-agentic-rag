"""Append-only, per-tenant hash-chained persistence for evidence envelopes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.runtime.evidence import build_evidence_envelope
from packages.platform_contracts.agent_runtime import AgentRunState
from packages.platform_contracts.evidence import EvidenceEnvelope

_MAX_ATTEMPTS = 5


class EvidenceStoreError(RuntimeError):
    pass


class EvidenceConflictError(EvidenceStoreError):
    """A different envelope already seals this run; envelopes are immutable."""


class EvidenceNotFoundError(LookupError):
    pass


class EvidenceChainError(EvidenceStoreError):
    pass


@dataclass(frozen=True)
class AppendedEvidence:
    chain_seq: int
    chain_hash: str
    created: bool


def _chain_hash(previous: str | None, fingerprint: str) -> str:
    return hashlib.sha256(f"{previous or ''}\0{fingerprint}".encode()).hexdigest()


class EvidenceStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, envelope: EvidenceEnvelope) -> AppendedEvidence:
        """Seal one terminal run. Idempotent for the identical envelope; conflicts otherwise."""
        for _ in range(_MAX_ATTEMPTS):
            try:
                with self.engine.begin() as connection:
                    return self._append(connection, envelope)
            except IntegrityError:
                continue  # lost a chain-sequence race (or a duplicate run); re-evaluate from scratch
        raise EvidenceStoreError("could not append evidence after repeated chain contention")

    def get(self, run_id: str, *, tenant_id: str, purpose: str) -> EvidenceEnvelope:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("""SELECT payload FROM analytics_evidence_envelopes
                    WHERE tenant_id=:tenant_id AND run_id=:run_id AND purpose=:purpose"""),
                    {"tenant_id": tenant_id, "run_id": run_id, "purpose": purpose},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise EvidenceNotFoundError("no evidence is sealed for this run in this tenant")
        return EvidenceEnvelope.model_validate(_load(row["payload"]))

    def verify_chain(self, tenant_id: str) -> int:
        """Recompute every link and content address for the tenant; returns the envelope count."""
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text("""SELECT chain_seq, run_id, purpose, content_fingerprint, previous_hash, chain_hash, payload
                    FROM analytics_evidence_envelopes WHERE tenant_id=:tenant_id ORDER BY chain_seq"""),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .all()
            )
        previous: str | None = None
        for expected_seq, row in enumerate(rows, start=1):
            try:
                envelope = EvidenceEnvelope.model_validate(_load(row["payload"]))
            except ValueError as exc:
                raise EvidenceChainError(f"envelope {expected_seq} fails validation") from exc
            if (
                row["chain_seq"] != expected_seq
                or row["previous_hash"] != previous
                or envelope.content_fingerprint != row["content_fingerprint"]
                or (envelope.tenant_id, envelope.run_id, envelope.purpose) != (tenant_id, row["run_id"], row["purpose"])
                or row["chain_hash"] != _chain_hash(previous, row["content_fingerprint"])
            ):
                raise EvidenceChainError(f"evidence chain is broken at sequence {expected_seq}")
            previous = row["chain_hash"]
        return len(rows)

    def _append(self, connection: Any, envelope: EvidenceEnvelope) -> AppendedEvidence:
        run = (
            connection.execute(
                text("""SELECT status FROM analytics_agent_runs
                WHERE run_id=:run_id AND tenant_id=:tenant_id AND purpose=:purpose"""),
                {"run_id": envelope.run_id, "tenant_id": envelope.tenant_id, "purpose": envelope.purpose},
            )
            .mappings()
            .first()
        )
        if run is None or run["status"] != "terminal":
            raise EvidenceStoreError("evidence can only seal an existing terminal run in the same tenant")
        existing = (
            connection.execute(
                text("""SELECT chain_seq, chain_hash, content_fingerprint FROM analytics_evidence_envelopes
                WHERE tenant_id=:tenant_id AND run_id=:run_id"""),
                {"tenant_id": envelope.tenant_id, "run_id": envelope.run_id},
            )
            .mappings()
            .first()
        )
        if existing:
            if existing["content_fingerprint"] != envelope.content_fingerprint:
                raise EvidenceConflictError("this run is already sealed with different evidence")
            return AppendedEvidence(existing["chain_seq"], existing["chain_hash"], created=False)
        tail = (
            connection.execute(
                text("""SELECT chain_seq, chain_hash FROM analytics_evidence_envelopes
                WHERE tenant_id=:tenant_id ORDER BY chain_seq DESC LIMIT 1"""),
                {"tenant_id": envelope.tenant_id},
            )
            .mappings()
            .first()
        )
        sequence = (tail["chain_seq"] if tail else 0) + 1
        previous = tail["chain_hash"] if tail else None
        chain_hash = _chain_hash(previous, envelope.content_fingerprint)
        connection.execute(
            text("""INSERT INTO analytics_evidence_envelopes
            (tenant_id, chain_seq, run_id, purpose, terminal_kind, content_fingerprint, previous_hash,
             chain_hash, payload)
            VALUES (:tenant_id, :chain_seq, :run_id, :purpose, :terminal_kind, :content_fingerprint,
                    :previous_hash, :chain_hash, :payload)"""),
            {
                "tenant_id": envelope.tenant_id,
                "chain_seq": sequence,
                "run_id": envelope.run_id,
                "purpose": envelope.purpose,
                "terminal_kind": envelope.terminal_kind,
                "content_fingerprint": envelope.content_fingerprint,
                "previous_hash": previous,
                "chain_hash": chain_hash,
                "payload": json.dumps(envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            },
        )
        return AppendedEvidence(sequence, chain_hash, created=True)


def record_terminal_evidence(
    control_store: Any, evidence_store: EvidenceStore, state: AgentRunState, *, validation: Any = None
) -> AppendedEvidence:
    """Seal a terminal run: replay its durable transitions, build the envelope, append it."""
    transitions = control_store.replay_transitions(
        run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose
    )
    return evidence_store.append(build_evidence_envelope(state, transitions, validation=validation))


def _load(payload: Any) -> Any:
    return json.loads(payload) if isinstance(payload, str) else payload
