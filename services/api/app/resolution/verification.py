"""Pure verification of grounded resolution output against authorized evidence."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from app.resolution.evidence import EvidencePacket
from app.resolution.models import GroundedResolutionOutcome

_WORD = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
_STOP = {"the", "and", "for", "with", "from", "this", "that", "may", "should", "after", "before"}
_NEGATION = re.compile(r"\b(?:not|never|cannot|can't|failed|failing|unsupported|do not|does not)\b", re.I)


class VerificationResult(BaseModel):
    """Immutable, provider-neutral result of deterministic verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    errors: tuple[str, ...] = ()
    allowed_labels: tuple[str, ...] = ()
    supported_claim_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)

    @property
    def verified(self) -> bool:
        return self.status == "verified"


def _terms(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.casefold()) if word not in _STOP}


def verify_resolution(outcome: GroundedResolutionOutcome, evidence: EvidencePacket) -> VerificationResult:
    """Verify citations, lineage, textual support, and abstention invariants."""
    errors: list[str] = []
    items = {item.label: item for item in evidence.items}
    allowed = tuple(item.label for item in evidence.items)
    citations = {citation.label: citation for citation in outcome.citations}

    unknown = sorted(set(citations) - set(items))
    if unknown:
        errors.append(f"unknown citation labels: {', '.join(unknown)}")
    for label, citation in citations.items():
        item = items.get(label)
        if item is not None and citation.source_id != item.source_id:
            errors.append(f"citation lineage mismatch for {label}")

    supported = 0
    cited_texts: list[str] = []
    for index, claim in enumerate(outcome.claims, start=1):
        claim_items = [items[label] for label in claim.citation_labels if label in items]
        if len(claim_items) != len(claim.citation_labels):
            errors.append(f"claim {index} references unknown evidence")
            continue
        if not claim_items or not all(item.snippet.strip() for item in claim_items):
            errors.append(f"claim {index} has blank or unsupported evidence")
            continue
        if not (_terms(claim.text) & set().union(*(_terms(item.snippet) for item in claim_items))):
            errors.append(f"claim {index} is unsupported by cited evidence")
            continue
        supported += 1
        cited_texts.extend(item.snippet for item in claim_items)
        if len(claim_items) > 1 and any(_NEGATION.search(item.snippet) for item in claim_items) and any(
            not _NEGATION.search(item.snippet) for item in claim_items
        ):
            errors.append(f"claim {index} cites conflicting evidence")

    for index, step in enumerate(outcome.steps, start=1):
        for label in step.citation_labels:
            if label not in items:
                errors.append(f"step {index} references unknown evidence: {label}")
        if step.citation_labels and not any(
            _terms(step.instruction) & _terms(items[label].snippet)
            for label in step.citation_labels
            if label in items
        ):
            errors.append(f"step {index} is unsupported by cited evidence")

    if outcome.action_proposal is not None and not any(
        _terms(outcome.action_proposal.description) & _terms(text) for text in cited_texts
    ):
        errors.append("action proposal is unsupported by cited evidence")
    if outcome.abstention:
        if outcome.next_action != "route_to_human":
            errors.append("abstention requires route_to_human")
        if outcome.action_proposal is not None:
            errors.append("abstention cannot include an action proposal")
    elif outcome.next_action == "route_to_human":
        errors.append("route_to_human requires abstention")

    return VerificationResult(
        status="verified" if not errors else "rejected",
        errors=tuple(dict.fromkeys(errors)), allowed_labels=allowed,
        supported_claim_count=supported, claim_count=len(outcome.claims),
    )


verify_grounded_resolution = verify_resolution

__all__ = ["VerificationResult", "verify_grounded_resolution", "verify_resolution"]
