"""ADS-052: proposal rules and the constraints the proposal contract itself enforces."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.proposals.rules import NoProposal, ProposalFacts, ProposalSpec, decide
from packages.platform_contracts.proposals import ChangeProposal, PatchOperation, apply_patch

BASE = {
    "triage_category": "semantic",
    "triage_rule_id": "T-91",
    "basis_kind": "both",
    "correction_id": "revenue",
    "target_kind": "metric",
    "target_dataset_id": "orders",
}


def _facts(**overrides):
    return ProposalFacts(**{**BASE, **overrides})


CASES = [
    ("definition disputed", _facts(), "flag_definition_for_review", "metric", "revenue", "P-10"),
    (
        "dimension definition disputed",
        _facts(correction_id="status", target_kind="dimension"),
        "flag_definition_for_review",
        "dimension",
        "status",
        "P-10",
    ),
    (
        "not retrieved",
        _facts(triage_category="retrieval", triage_rule_id="T-90"),
        "add_context_edge",
        "metric",
        "revenue",
        "P-20",
    ),
    (
        "missing context with a correction",
        _facts(triage_category="retrieval", triage_rule_id="T-80"),
        "add_context_edge",
        "metric",
        "revenue",
        "P-20",
    ),
    (
        "label collision",
        _facts(
            triage_category="ontology",
            triage_rule_id="T-30",
            correction_id=None,
            target_kind=None,
            collision_code="time",
            collision_candidates=("status", "created_at"),
        ),
        "review_label_collision",
        "ontology_label",
        "time",
        "P-30",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_each_rule_proposes_the_documented_operation(case):
    _, facts, operation, target_kind, target_id, rule = case
    decision = decide(facts)
    assert isinstance(decision, ProposalSpec)
    assert (decision.operation, decision.target_kind, decision.target_id, decision.rule_id) == (
        operation,
        target_kind,
        target_id,
        rule,
    )
    assert decide(facts) == decision  # deterministic


def test_the_collision_proposal_lists_its_candidates_sorted():
    decision = decide(CASES[-1][1])
    assert decision.parameters == {"candidates": "created_at,status"}


NONE = [
    ("reporter claim only", _facts(basis_kind="reporter_claim"), "claim_only"),
    ("undetermined triage", _facts(triage_category="undetermined", triage_rule_id="T-92"), "category_not_applicable"),
    (
        "policy fault",
        _facts(triage_category="policy", triage_rule_id="T-10", basis_kind="system_evidence"),
        "category_not_applicable",
    ),
    (
        "execution fault",
        _facts(triage_category="execution", triage_rule_id="T-40", basis_kind="system_evidence"),
        "category_not_applicable",
    ),
    (
        "retrieval from a provider failure",
        _facts(triage_category="retrieval", triage_rule_id="T-35", basis_kind="system_evidence"),
        "category_not_applicable",
    ),
    ("semantic without a target", _facts(correction_id=None, target_kind=None), "no_target"),
    (
        "retrieval of an unknown dataset",
        _facts(triage_category="retrieval", triage_rule_id="T-90", target_dataset_id=None),
        "unknown_dataset",
    ),
    (
        "collision without candidates",
        _facts(triage_category="ontology", triage_rule_id="T-30", basis_kind="system_evidence"),
        "no_target",
    ),
]


@pytest.mark.parametrize("case", NONE, ids=[c[0] for c in NONE])
def test_everything_else_produces_no_proposal_with_a_reason(case):
    _, facts, reason = case
    assert decide(facts) == NoProposal(reason)


def test_a_patch_cannot_certify_or_touch_definitions_policies_or_anything_but_the_allowed_paths():
    PatchOperation(op="replace", path="/lifecycle", value="draft")
    for path, value in (
        ("/lifecycle", "certified"),
        ("/lifecycle", "deprecated"),
        ("/contract/metrics", []),
        ("/contract/policies", []),
        ("/contract/datasets/0", {}),
        ("/contract/id", "x"),
        ("/contract/tenant_id", "t"),
    ):
        with pytest.raises(ValidationError):
            PatchOperation(op="add", path=path, value=value)


def _proposal(**overrides):
    from datetime import datetime, timezone

    fields = dict(
        proposal_id="p" * 8,
        tenant_id="t",
        kind="semantic_context",
        operation="flag_definition_for_review",
        target_kind="metric",
        target_id="revenue",
        parameters={},
        base_contract="sales-core@v1",
        base_contract_fingerprint="a" * 64,
        draft_version="v1-d",
        rationale_codes=("rule:P-10",),
        origin_triage_id="tr",
        origin_feedback_id="fb",
        origin_run_id="run",
        rules_version="proposal-rules-v1",
        created_at=datetime.now(timezone.utc),
        content_fingerprint="b" * 64,
    )
    fields.update(overrides)
    return ChangeProposal(**fields)


def test_a_proposal_is_always_proposed_never_applied_and_targets_identifiers_only():
    lifecycle = PatchOperation(op="replace", path="/lifecycle", value="draft")
    version = PatchOperation(op="replace", path="/contract/version", value="v1-d")
    good = _proposal(draft_patch=(lifecycle, version))
    assert good.status == "proposed" and good.created_by == "system:proposal-generator"
    with pytest.raises(ValidationError):
        _proposal(status="approved")
    with pytest.raises(ValidationError):
        _proposal(created_by="someone")
    with pytest.raises(ValidationError):
        _proposal(draft_patch=(version,))  # a patch must say it is a draft
    with pytest.raises(ValidationError):
        _proposal(draft_patch=(lifecycle,), draft_version=None)
    for bad in ("revenue; DROP TABLE x", "SUM(amount)", "a b", ""):
        with pytest.raises(ValidationError):
            _proposal(target_id=bad)


def test_apply_patch_returns_a_copy_and_never_mutates_its_input():
    document = {"lifecycle": "certified", "contract": {"version": "v1", "metadata": {}}}
    patch = (
        PatchOperation(op="replace", path="/lifecycle", value="draft"),
        PatchOperation(op="add", path="/contract/metadata", value={"review_flags": {"revenue": "definition_disputed"}}),
    )
    patched = apply_patch(document, patch)
    assert patched["lifecycle"] == "draft" and patched["contract"]["metadata"]["review_flags"]
    assert document == {"lifecycle": "certified", "contract": {"version": "v1", "metadata": {}}}
