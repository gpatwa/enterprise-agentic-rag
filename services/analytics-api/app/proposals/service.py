"""Generate change proposals from triage records and store them append-only (ADS-052).

The generator reads the certified contract and writes only to the proposal tables. It has no handle
on the registry directory, the goldens, the thresholds, or the runtime prompt, and it never applies
a patch: a patch is a value on the proposal for a reviewer to look at.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.proposals.rules import NoProposal, ProposalFacts, ProposalSpec, decide
from app.runtime.control_store import ControlStoreError
from app.runtime.evidence_store import EvidenceNotFoundError, EvidenceStore
from app.runtime.feedback_store import FeedbackNotFoundError, FeedbackStore
from app.triage.service import TriageError, TriageStore
from packages.platform_contracts.proposals import (
    PROPOSAL_RULES_VERSION,
    ChangeProposal,
    PatchOperation,
    apply_patch,
    proposal_fingerprint,
)


class ProposalError(RuntimeError):
    """The proposal cannot be generated; the message names the missing input, never run content."""


class ProposalConflictError(ProposalError):
    """An existing proposal with this ID has different content."""


@dataclass(frozen=True)
class GenerationResult:
    proposal: ChangeProposal | None
    reason: str | None
    proposal_created: bool = False
    support_added: bool = False


class ProposalStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, proposal: ChangeProposal, *, triage_id: str, feedback_id: str) -> tuple[bool, bool]:
        """(proposal_created, support_added). Content is immutable; extra support only adds a link."""
        for _ in range(2):
            try:
                with self.engine.begin() as connection:
                    existing = self._get(connection, proposal.tenant_id, proposal.proposal_id)
                    created = existing is None
                    if existing is not None and existing.content_fingerprint != proposal.content_fingerprint:
                        raise ProposalConflictError("this proposal ID already exists with different content")
                    if created:
                        connection.execute(
                            text("""INSERT INTO analytics_change_proposals
                            (tenant_id, proposal_id, kind, operation, target_id, base_contract,
                             content_fingerprint, payload)
                            VALUES (:tenant_id, :proposal_id, :kind, :operation, :target_id, :base_contract,
                                    :content_fingerprint, :payload)"""),
                            {
                                "tenant_id": proposal.tenant_id,
                                "proposal_id": proposal.proposal_id,
                                "kind": proposal.kind,
                                "operation": proposal.operation,
                                "target_id": proposal.target_id,
                                "base_contract": proposal.base_contract,
                                "content_fingerprint": proposal.content_fingerprint,
                                "payload": json.dumps(
                                    proposal.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                                ),
                            },
                        )
                    linked = connection.execute(
                        text("""SELECT 1 FROM analytics_proposal_support
                        WHERE tenant_id=:t AND proposal_id=:p AND triage_id=:g"""),
                        {"t": proposal.tenant_id, "p": proposal.proposal_id, "g": triage_id},
                    ).first()
                    if linked is None:
                        connection.execute(
                            text("""INSERT INTO analytics_proposal_support (tenant_id, proposal_id, triage_id, feedback_id)
                            VALUES (:t, :p, :g, :f)"""),
                            {"t": proposal.tenant_id, "p": proposal.proposal_id, "g": triage_id, "f": feedback_id},
                        )
                    return created, linked is None
            except IntegrityError:
                continue
        raise ProposalError("could not append the proposal after repeated contention")

    def get(self, proposal_id: str, *, tenant_id: str) -> ChangeProposal:
        with self.engine.connect() as connection:
            proposal = self._get(connection, tenant_id, proposal_id)
        if proposal is None:
            raise ProposalError("no such proposal in this tenant")
        return proposal

    def support(self, proposal_id: str, *, tenant_id: str) -> tuple[str, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("""SELECT triage_id FROM analytics_proposal_support WHERE tenant_id=:t AND proposal_id=:p
                ORDER BY created_at, triage_id"""),
                {"t": tenant_id, "p": proposal_id},
            ).all()
        return tuple(row[0] for row in rows)

    def list(self, *, tenant_id: str) -> tuple[ChangeProposal, ...]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT payload FROM analytics_change_proposals WHERE tenant_id=:t ORDER BY created_at, proposal_id"
                    ),
                    {"t": tenant_id},
                )
                .mappings()
                .all()
            )
        return tuple(ChangeProposal.model_validate(_load(row["payload"])) for row in rows)

    @staticmethod
    def _get(connection: Any, tenant_id: str, proposal_id: str) -> ChangeProposal | None:
        row = (
            connection.execute(
                text("SELECT payload FROM analytics_change_proposals WHERE tenant_id=:t AND proposal_id=:p"),
                {"t": tenant_id, "p": proposal_id},
            )
            .mappings()
            .first()
        )
        return ChangeProposal.model_validate(_load(row["payload"])) if row else None


class ProposalService:
    def __init__(
        self,
        control_store: Any,
        evidence_store: EvidenceStore,
        feedback_store: FeedbackStore,
        triage_store: TriageStore,
        store: ProposalStore,
        contracts: Any,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.control, self.evidence, self.feedback, self.triage, self.store, self.contracts, self.now = (
            control_store,
            evidence_store,
            feedback_store,
            triage_store,
            store,
            contracts,
            now,
        )

    def generate(self, triage_id: str, *, tenant_id: str) -> GenerationResult:
        """Turn one triage record into a proposal, or say why not. Idempotent; applies nothing."""
        try:
            record = self.triage.get(triage_id, tenant_id=tenant_id)
            feedback = self.feedback.get(record.feedback_id, tenant_id=tenant_id)
            envelope = self.evidence.get(record.run_id, tenant_id=tenant_id, purpose=record.purpose)
            state = self.control.load_latest_checkpoint(
                run_id=record.run_id, tenant_id=tenant_id, purpose=record.purpose
            )
            # A run that never resolved a contract, or a fault that is not ours to propose a fix for, ends
            # here with a reason; the contract is only needed once a proposal is actually warranted.
            early = decide(ProposalFacts(record.category, record.rule_id, record.basis_kind))
            if isinstance(early, NoProposal) and early.reason in {"claim_only", "category_not_applicable"}:
                return GenerationResult(None, early.reason)
            contract_ref = envelope.semantic_contract or ""
            contract_id, _, version = contract_ref.rpartition("@")
            document = self.contracts.get_certified(contract_id, version)
        except (
            FeedbackNotFoundError,
            EvidenceNotFoundError,
            ControlStoreError,
            LookupError,
            ProposalError,
            TriageError,
        ) as exc:
            raise ProposalError("triage, feedback, evidence, run, or contract is not available") from exc
        contract = document.contract
        target_kind, dataset_id = _locate(contract, feedback.correction.semantic_id if feedback.correction else None)
        clarification = (state.clarification_state or {}).get("ambiguities") or []
        facts = ProposalFacts(
            triage_category=record.category,
            triage_rule_id=record.rule_id,
            basis_kind=record.basis_kind,
            correction_id=feedback.correction.semantic_id if feedback.correction else None,
            target_kind=target_kind,
            target_dataset_id=dataset_id,
            collision_code=clarification[0]["code"] if clarification else None,
            collision_candidates=tuple(clarification[0]["candidate_ids"]) if clarification else (),
        )
        decision = decide(facts)
        if isinstance(decision, NoProposal):
            return GenerationResult(None, decision.reason)
        base_document = document.model_dump(mode="json")
        base_fingerprint = hashlib.sha256(
            json.dumps(base_document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        fingerprint = proposal_fingerprint(
            kind="semantic_context",
            operation=decision.operation,
            target_kind=decision.target_kind,
            target_id=decision.target_id,
            parameters=decision.parameters,
            base_contract=contract_ref,
            base_contract_fingerprint=base_fingerprint,
            rules_version=PROPOSAL_RULES_VERSION,
        )
        proposal = self._build(decision, record, contract_ref, base_document, base_fingerprint, fingerprint)
        created, linked = self.store.append(proposal, triage_id=triage_id, feedback_id=record.feedback_id)
        return GenerationResult(self.store.get(proposal.proposal_id, tenant_id=tenant_id), None, created, linked)

    def preview_diff(self, proposal_id: str, *, tenant_id: str) -> str:
        """A unified diff of the draft against the certified contract it was proposed from."""
        proposal = self.store.get(proposal_id, tenant_id=tenant_id)
        if not proposal.draft_patch:
            return ""
        contract_id, _, version = proposal.base_contract.rpartition("@")
        before = self.contracts.get_certified(contract_id, version).model_dump(mode="json")
        after = apply_patch(before, proposal.draft_patch)
        render = lambda doc: json.dumps(doc, indent=2, sort_keys=True).splitlines()  # noqa: E731
        return "\n".join(
            difflib.unified_diff(
                render(before),
                render(after),
                f"{proposal.base_contract} (certified)",
                f"{proposal.draft_version} (draft)",
                lineterm="",
            )
        )

    def _build(
        self, spec: ProposalSpec, record: Any, contract_ref: str, base: dict, base_fp: str, fingerprint: str
    ) -> ChangeProposal:
        patch: tuple[PatchOperation, ...] = ()
        draft_version: str | None = None
        note: str | None = None
        if spec.operation == "flag_definition_for_review":
            draft_version = f"{base['contract']['version']}-proposal-{fingerprint[:8]}"
            metadata = json.loads(json.dumps(base["contract"].get("metadata") or {}))
            metadata.setdefault("review_flags", {})[spec.target_id] = spec.parameters["reason"]
            patch = (
                PatchOperation(op="replace", path="/lifecycle", value="draft"),
                PatchOperation(op="replace", path="/contract/version", value=draft_version),
                PatchOperation(op="add", path="/contract/metadata", value=metadata),
            )
        else:
            note = "No registry representation: this change belongs to the generated ontology/context, not a contract file."
        fields = dict(
            proposal_id=fingerprint[:32],
            tenant_id=record.tenant_id,
            kind="semantic_context",
            operation=spec.operation,
            target_kind=spec.target_kind,
            target_id=spec.target_id,
            parameters=spec.parameters,
            base_contract=contract_ref,
            base_contract_fingerprint=base_fp,
            draft_version=draft_version,
            draft_patch=patch,
            patch_note=note,
            rationale_codes=spec.rationale_codes + (f"rule:{spec.rule_id}",),
            origin_triage_id=record.triage_id,
            origin_feedback_id=record.feedback_id,
            origin_run_id=record.run_id,
            rules_version=PROPOSAL_RULES_VERSION,
            created_at=self.now(),
        )
        draft = ChangeProposal(**fields, content_fingerprint="0" * 64)
        # The fingerprint covers what is being asked for, not who raised it: the origin links name the first
        # triage that created the proposal and every later one is recorded as support, so duplicates match.
        excluded = {"content_fingerprint", "created_at", "origin_triage_id", "origin_feedback_id", "origin_run_id"}
        content = {k: v for k, v in draft.model_dump(mode="json").items() if k not in excluded}
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return ChangeProposal(**fields, content_fingerprint=digest)


def _locate(contract: Any, semantic_id: str | None) -> tuple[str | None, str | None]:
    """(kind, dataset) of a certified ID, or (None, None)."""
    if not semantic_id:
        return None, None
    for kind, items in (("metric", contract.metrics), ("dimension", contract.dimensions), ("field", contract.fields)):
        for item in items:
            if item.id == semantic_id:
                return kind, getattr(item, "dataset_id", None)
    return None, None


def _load(payload: Any) -> Any:
    return json.loads(payload) if isinstance(payload, str) else payload
