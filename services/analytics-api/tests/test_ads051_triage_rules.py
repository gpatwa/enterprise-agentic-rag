"""ADS-051: the deterministic triage rules, table-driven over structured inputs."""

from __future__ import annotations

import dataclasses

import pytest

from app.triage.rules import TriageInputs, triage_decision
from packages.platform_contracts.triage import FAULT_CATEGORIES

CTX = frozenset({"orders", "revenue", "status", "created_at"})
USED = frozenset({"revenue", "created_at", "orders.status"})


def _in(**kwargs):
    base = {
        "verdict": "incorrect",
        "reason_code": "other",
        "context_ids": CTX,
        "used_ids": USED,
        "validation_status": "valid",
        "policy_effect": "allow",
    }
    base.update(kwargs)
    return TriageInputs(**base)


# (case id, inputs, category, rule, basis_kind, conflict)
CASES = [
    ("correct", _in(verdict="correct"), "none", "T-00", "none", False),
    (
        "correct even if the run failed",
        _in(verdict="correct", terminal_kind="failed", error_codes=("policy_denied",)),
        "none",
        "T-00",
        "none",
        False,
    ),
    ("cancelled", _in(terminal_kind="cancelled"), "none", "T-05", "system_evidence", False),
    (
        "policy denial",
        _in(terminal_kind="refused", error_codes=("policy_denied",), policy_effect="deny", validation_status=None),
        "policy",
        "T-10",
        "system_evidence",
        False,
    ),
    (
        "policy denial blamed on the metric",
        _in(
            reason_code="wrong_metric", terminal_kind="refused", error_codes=("policy_denied",), validation_status=None
        ),
        "policy",
        "T-10",
        "system_evidence",
        True,
    ),
    (
        "malformed intent",
        _in(
            reason_code="wrong_metric",
            terminal_kind="failed",
            error_codes=("malformed_model_output",),
            validation_status=None,
        ),
        "intent",
        "T-20",
        "system_evidence",
        False,
    ),
    (
        "malformed intent blamed on context",
        _in(
            reason_code="missing_context",
            terminal_kind="failed",
            error_codes=("malformed_model_output",),
            validation_status=None,
        ),
        "intent",
        "T-20",
        "system_evidence",
        True,
    ),
    (
        "ontology failure",
        _in(
            terminal_kind="refused",
            error_codes=("stale_context",),
            error_references=("ontology:unknown_or_uncertified_semantic_id",),
            validation_status=None,
        ),
        "ontology",
        "T-30",
        "system_evidence",
        False,
    ),
    (
        "clarification exhausted",
        _in(
            terminal_kind="refused",
            error_codes=("stale_context",),
            error_references=("clarification:ClarificationError",),
            validation_status=None,
        ),
        "ontology",
        "T-30",
        "system_evidence",
        False,
    ),
    (
        "context provider failure",
        _in(
            terminal_kind="refused",
            error_codes=("stale_context",),
            error_references=("context_provider:TimeoutError",),
            validation_status=None,
        ),
        "retrieval",
        "T-35",
        "system_evidence",
        False,
    ),
    (
        "invalid result",
        _in(
            terminal_kind="failed",
            error_codes=("result_invalid",),
            validation_status="invalid",
            validation_issue_codes=("fanout_suspected",),
        ),
        "execution",
        "T-40",
        "system_evidence",
        False,
    ),
    (
        "budget exceeded",
        _in(terminal_kind="failed", error_codes=("cost_budget_exceeded",), validation_status=None),
        "execution",
        "T-40",
        "system_evidence",
        False,
    ),
    (
        "explanation failed",
        _in(terminal_kind="failed", error_codes=("explain_result_invalid",)),
        "prose",
        "T-50",
        "system_evidence",
        False,
    ),
    ("unclear explanation", _in(reason_code="unclear_explanation"), "prose", "T-60", "both", False),
    (
        "unclear explanation without a validated result",
        _in(reason_code="unclear_explanation", validation_status=None),
        "prose",
        "T-60",
        "reporter_claim",
        False,
    ),
    ("policy concern", _in(reason_code="policy_concern", verdict="unsafe"), "policy", "T-70", "reporter_claim", False),
    ("unsafe verdict alone", _in(verdict="unsafe"), "policy", "T-70", "reporter_claim", False),
    (
        "missing context, id absent",
        _in(reason_code="missing_context", correction_target="metric", correction_id="margin"),
        "retrieval",
        "T-80",
        "both",
        False,
    ),
    (
        "missing context, no correction",
        _in(reason_code="missing_context"),
        "retrieval",
        "T-80",
        "reporter_claim",
        False,
    ),
    (
        "missing context but the id was retrieved",
        _in(reason_code="missing_context", correction_target="metric", correction_id="revenue"),
        "undetermined",
        "T-81",
        "both",
        True,
    ),
    ("stale data", _in(reason_code="stale_data"), "undetermined", "T-85", "reporter_claim", False),
    (
        "correction not retrieved",
        _in(reason_code="wrong_filter", correction_target="dimension", correction_id="region"),
        "retrieval",
        "T-90",
        "both",
        False,
    ),
    (
        "correction omitted by budget",
        _in(
            reason_code="wrong_filter",
            correction_target="dimension",
            correction_id="status",
            omitted_ids=frozenset({"status"}),
        ),
        "retrieval",
        "T-90",
        "both",
        False,
    ),
    (
        "correction already used",
        _in(reason_code="wrong_metric", correction_target="metric", correction_id="revenue"),
        "semantic",
        "T-91",
        "both",
        False,
    ),
    (
        "correction retrieved but not used",
        _in(reason_code="wrong_metric", correction_target="dimension", correction_id="status"),
        "undetermined",
        "T-92",
        "both",
        False,
    ),
    ("wrong grain, no correction", _in(reason_code="wrong_grain"), "undetermined", "T-95", "reporter_claim", False),
    ("other, no correction", _in(reason_code="other"), "undetermined", "T-99", "reporter_claim", False),
    (
        "unrecognised failure",
        _in(terminal_kind="failed", error_codes=("brand_new_code",), validation_status=None),
        "undetermined",
        "T-09",
        "system_evidence",
        False,
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_each_rule_decides_as_documented(case):
    _, inputs, category, rule_id, basis, conflict = case
    decision = triage_decision(inputs)
    assert (decision.category, decision.rule_id, decision.basis_kind, decision.conflict) == (
        category,
        rule_id,
        basis,
        conflict,
    )
    assert decision.evidence_basis and (decision.category != "undetermined" or decision.alternates)
    assert triage_decision(inputs) == decision  # deterministic


def test_every_documented_rule_is_covered_and_undetermined_always_lists_candidates():
    rules = {c[3] for c in CASES}
    assert rules >= {
        "T-00",
        "T-05",
        "T-09",
        "T-10",
        "T-20",
        "T-30",
        "T-35",
        "T-40",
        "T-50",
        "T-60",
        "T-70",
        "T-80",
        "T-81",
        "T-85",
        "T-90",
        "T-91",
        "T-92",
        "T-95",
        "T-99",
    }
    for _, inputs, category, *_ in CASES:
        if category == "undetermined":
            assert set(triage_decision(inputs).alternates) <= set(FAULT_CATEGORIES)


def test_system_evidence_outranks_the_reporters_claim_and_priority_is_fixed():
    both = _in(
        reason_code="unclear_explanation",
        terminal_kind="failed",
        error_codes=("result_invalid", "policy_denied", "malformed_model_output"),
    )
    decision = triage_decision(both)
    assert decision.category == "policy" and decision.conflict and decision.basis_kind == "system_evidence"
    without_policy = dataclasses.replace(both, error_codes=("result_invalid", "malformed_model_output"))
    assert triage_decision(without_policy).category == "intent"


def test_the_inputs_have_no_free_text_field_so_a_note_cannot_steer_triage():
    fields = {f.name: f.type for f in dataclasses.fields(TriageInputs)}
    assert "note" not in fields
    # Every string-typed input is a closed code or an identifier, never prose.
    strings = {
        name
        for name, kind in fields.items()
        if "str" in str(kind) and "tuple" not in str(kind) and "frozenset" not in str(kind)
    }
    assert strings == {
        "verdict",
        "reason_code",
        "correction_target",
        "correction_id",
        "terminal_kind",
        "validation_status",
        "policy_effect",
    }
