"""Deterministic proposal rules (ADS-052, `proposal-rules-v1`).

Pure code over structured fields: no model, no free text. A proposal is generated only when the
triage decision rests on system evidence (basis `both` or `system_evidence`) *and* names a concrete
certified target. The operation list is closed: flag a definition for review, ask for a context
edge, or flag a label collision. A rewritten definition is never proposed; that needs a person.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.platform_contracts.proposals import ProposalOperation, TargetKind


@dataclass(frozen=True)
class ProposalFacts:
    triage_category: str
    triage_rule_id: str
    basis_kind: str
    correction_id: str | None = None
    target_kind: str | None = None  # kind of the correction's target in the contract
    target_dataset_id: str | None = None
    collision_code: str | None = None
    collision_candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProposalSpec:
    operation: ProposalOperation
    target_kind: TargetKind
    target_id: str
    parameters: dict[str, str]
    rationale_codes: tuple[str, ...]
    rule_id: str


@dataclass(frozen=True)
class NoProposal:
    reason: str


def decide(facts: ProposalFacts) -> ProposalSpec | NoProposal:
    if facts.basis_kind not in {"both", "system_evidence"}:
        return NoProposal("claim_only")
    if facts.triage_category == "semantic" and facts.triage_rule_id == "T-91":
        if not facts.correction_id or not facts.target_kind:
            return NoProposal("no_target")
        return ProposalSpec(
            "flag_definition_for_review",
            facts.target_kind,  # type: ignore[arg-type]
            facts.correction_id,
            {"reason": "definition_disputed"},
            ("triage:T-91", "correction:used_by_intent"),
            "P-10",
        )
    if facts.triage_category == "retrieval" and facts.triage_rule_id in {"T-90", "T-80"}:
        if not facts.correction_id or not facts.target_kind:
            return NoProposal("no_target")
        if not facts.target_dataset_id:
            return NoProposal("unknown_dataset")
        return ProposalSpec(
            "add_context_edge",
            facts.target_kind,  # type: ignore[arg-type]
            facts.correction_id,
            {"dataset_id": facts.target_dataset_id, "edge_type": "contains"},
            (f"triage:{facts.triage_rule_id}", "correction:not_in_context"),
            "P-20",
        )
    if facts.triage_category == "ontology" and facts.triage_rule_id == "T-30":
        if not facts.collision_code or not facts.collision_candidates:
            return NoProposal("no_target")
        return ProposalSpec(
            "review_label_collision",
            "ontology_label",
            facts.collision_code,
            {"candidates": ",".join(sorted(facts.collision_candidates))},
            ("triage:T-30", "clarification:exhausted"),
            "P-30",
        )
    return NoProposal("category_not_applicable")
