"""Ordered, deterministic triage rules (ADS-051, rules version `triage-rules-v1`).

Pure code: no model, no I/O, no free text. The inputs are structured fields only; the feedback note
is deliberately not an input, so it cannot steer a classification. System evidence (the run's own
errors, validation, and policy decision) outranks the reporter's claim. When the two disagree the
system's category wins and `conflict` is set; when nothing decides, the result is `undetermined`
and lists its candidate causes for a human.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.platform_contracts.triage import FAULT_CATEGORIES, BasisKind, RootCause

_POLICY_CODES = {"policy_denied"}
_INTENT_PREFIXES = ("malformed_model_output", "intent_")
_EXECUTION_CODES = {
    "result_invalid",
    "control_query_failed",
    "result_inputs_unavailable",
    "run_deadline_exceeded",
    "cost_budget_exceeded",
    "transition_budget_exceeded",
    "node_exception",
    "invalid_cost_observation",
    "review_creation_failed",
    "review_store_unavailable",
}
_HINTS: dict[str, frozenset[str]] = {
    "wrong_metric": frozenset({"intent", "ontology", "semantic"}),
    "wrong_filter": frozenset({"intent", "ontology", "semantic"}),
    "wrong_time_range": frozenset({"intent", "ontology", "semantic"}),
    "wrong_grain": frozenset({"intent", "ontology", "semantic"}),
    "missing_context": frozenset({"retrieval"}),
    "stale_data": frozenset({"retrieval", "execution"}),
    "policy_concern": frozenset({"policy"}),
    "unclear_explanation": frozenset({"prose"}),
}
_WRONG = ("wrong_metric", "wrong_filter", "wrong_time_range", "wrong_grain")


@dataclass(frozen=True)
class TriageInputs:
    """Everything a rule may look at. There is intentionally no `note` field."""

    verdict: str
    reason_code: str
    correction_target: str | None = None
    correction_id: str | None = None
    terminal_kind: str = "succeeded"
    error_codes: tuple[str, ...] = ()
    error_references: tuple[str, ...] = ()
    validation_status: str | None = None
    validation_issue_codes: tuple[str, ...] = ()
    policy_effect: str | None = None
    used_ids: frozenset[str] = field(default_factory=frozenset)
    context_ids: frozenset[str] = field(default_factory=frozenset)
    omitted_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class TriageDecision:
    category: RootCause
    rule_id: str
    basis_kind: BasisKind
    evidence_basis: tuple[str, ...] = ()
    alternates: tuple[RootCause, ...] = ()
    conflict: bool = False


def triage_decision(inputs: TriageInputs) -> TriageDecision:
    if inputs.verdict == "correct":
        return TriageDecision("none", "T-00", "none", ("verdict:correct",))
    if inputs.terminal_kind == "cancelled":
        return TriageDecision("none", "T-05", "system_evidence", ("terminal:cancelled",))
    system = _system_evidence(inputs)
    if system is not None:
        category, rule_id, basis = system
        hint = set(_HINTS.get(inputs.reason_code, ())) | ({"policy"} if inputs.verdict == "unsafe" else set())
        conflict = bool(hint) and category not in hint  # the reporter blamed somewhere the evidence does not
        return TriageDecision(category, rule_id, "system_evidence", basis, (), conflict)
    if inputs.terminal_kind != "succeeded":
        # The run did not succeed but no rule recognises why: say so rather than guess.
        basis = tuple(f"error:{code}" for code in inputs.error_codes) or (f"terminal:{inputs.terminal_kind}",)
        return TriageDecision("undetermined", "T-09", "system_evidence", basis, _all_faults())
    return _reporter_claim(inputs)


def _system_evidence(inputs: TriageInputs) -> tuple[RootCause, str, tuple[str, ...]] | None:
    codes = inputs.error_codes
    errors = tuple(f"error:{code}" for code in codes)
    refs = inputs.error_references
    validation = (f"validation:{inputs.validation_status}",) if inputs.validation_status else ()
    issues = tuple(f"validation_issue:{code}" for code in inputs.validation_issue_codes)
    if any(code in _POLICY_CODES for code in codes) or inputs.policy_effect == "deny":
        return "policy", "T-10", errors + ((f"policy:{inputs.policy_effect}",) if inputs.policy_effect else ())
    if any(code.startswith(_INTENT_PREFIXES) for code in codes):
        return "intent", "T-20", errors
    if "stale_context" in codes:
        if any(ref.startswith(("ontology:", "clarification:")) for ref in refs):
            return "ontology", "T-30", errors
        return "retrieval", "T-35", errors
    if any(code in _EXECUTION_CODES for code in codes) or inputs.validation_status == "invalid":
        return "execution", "T-40", errors + validation + issues
    if any(code.startswith("explain_") for code in codes):
        return "prose", "T-50", errors
    return None


def _reporter_claim(inputs: TriageInputs) -> TriageDecision:
    """The run succeeded and validated, so only the reporter's structured claim is available."""
    reason = inputs.reason_code
    valid = inputs.validation_status in {"valid", "valid_with_warnings"}
    claim = (f"reason:{reason}", f"verdict:{inputs.verdict}")
    if reason == "unclear_explanation":
        basis = claim + ((f"validation:{inputs.validation_status}",) if valid else ())
        return TriageDecision("prose", "T-60", "both" if valid else "reporter_claim", basis)
    if reason == "policy_concern" or inputs.verdict == "unsafe":
        effect = (f"policy:{inputs.policy_effect}",) if inputs.policy_effect else ()
        return TriageDecision("policy", "T-70", "reporter_claim", claim + effect)
    cid = inputs.correction_id
    if reason == "missing_context":
        if cid is None or cid in inputs.omitted_ids or cid not in inputs.context_ids:
            flag = ("correction:not_in_context",) if cid else ()
            return TriageDecision("retrieval", "T-80", "both" if cid else "reporter_claim", claim + flag)
        return TriageDecision(
            "undetermined", "T-81", "both", claim + ("correction:in_context",), ("intent", "ontology"), True
        )
    if reason == "stale_data":
        return TriageDecision("undetermined", "T-85", "reporter_claim", claim, ("retrieval", "execution"))
    if reason in _WRONG or (reason == "other" and cid is not None):
        if cid is None:
            return TriageDecision("undetermined", "T-95", "reporter_claim", claim, ("intent", "ontology", "semantic"))
        if cid in inputs.omitted_ids or cid not in inputs.context_ids:
            return TriageDecision("retrieval", "T-90", "both", claim + ("correction:not_in_context",))
        if cid in inputs.used_ids:
            return TriageDecision("semantic", "T-91", "both", claim + ("correction:used_by_intent",))
        return TriageDecision(
            "undetermined", "T-92", "both", claim + ("correction:in_context_not_used",), ("intent", "ontology")
        )
    return TriageDecision("undetermined", "T-99", "reporter_claim", claim, _all_faults())


def _all_faults() -> tuple[RootCause, ...]:
    return tuple(FAULT_CATEGORIES)  # type: ignore[return-value]
