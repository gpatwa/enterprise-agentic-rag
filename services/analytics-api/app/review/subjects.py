"""Resolve what is being reviewed and who contributed to it (ADS-055). Read-only."""

from __future__ import annotations

from typing import Any

from app.prompt_registry import PromptRegistry, RegistryNotFoundError
from app.proposals.service import ProposalError, ProposalStore
from app.review.rules import ReviewError
from app.runtime.feedback_store import FeedbackNotFoundError, FeedbackStore
from app.triage.service import TriageError, TriageStore
from packages.platform_contracts.review import ReviewSubject


class SubjectResolver:
    def __init__(
        self, proposals: ProposalStore, registry: PromptRegistry, triage: TriageStore, feedback: FeedbackStore
    ) -> None:
        self.proposals, self.registry, self.triage, self.feedback = proposals, registry, triage, feedback

    def resolve(self, kind: str, subject_id: str, *, tenant_id: str) -> ReviewSubject:
        """The subject as it is now. Every contributor is included: the generator and each feedback submitter."""
        try:
            if kind == "change_proposal":
                proposal = self.proposals.get(subject_id, tenant_id=tenant_id)
                triage_ids = self.proposals.support(subject_id, tenant_id=tenant_id) or (proposal.origin_triage_id,)
                contributors = {proposal.created_by} | self._submitters(triage_ids, tenant_id)
                return ReviewSubject(
                    kind=kind,
                    subject_id=subject_id,
                    content_fingerprint=proposal.content_fingerprint,
                    contributor_ids=tuple(sorted(contributors)),
                )
            name, _, version = subject_id.partition("@")
            if kind == "prompt_candidate":
                entry: Any = self.registry.get("prompt", name, version, tenant_id=tenant_id)
                if entry.status != "candidate":
                    raise ReviewError("not_reviewable")
                contributors = {entry.created_by} | self._submitters(entry.origin_triage_ids, tenant_id)
            elif kind == "example_candidate":
                entry = self.registry.get("example", name, version, tenant_id=tenant_id)
                contributors = {entry.created_by} | {
                    self.feedback.get(entry.source_feedback_id, tenant_id=tenant_id).submitted_by
                }
            else:
                raise ReviewError("unknown_subject_kind")
        except (ProposalError, RegistryNotFoundError, TriageError, FeedbackNotFoundError) as exc:
            raise ReviewError("subject_not_found") from exc
        return ReviewSubject(
            kind=kind,
            subject_id=subject_id,
            content_fingerprint=entry.content_fingerprint,
            contributor_ids=tuple(sorted(contributors)),
        )

    def _submitters(self, triage_ids: tuple[str, ...], tenant_id: str) -> set[str]:
        out: set[str] = set()
        for triage_id in triage_ids:
            record = self.triage.get(triage_id, tenant_id=tenant_id)
            out.add(self.feedback.get(record.feedback_id, tenant_id=tenant_id).submitted_by)
        return out
