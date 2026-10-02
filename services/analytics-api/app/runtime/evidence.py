"""Assemble the evidence envelope for a terminal run from its state and transition history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.execution.result_validation import ResultValidationReport
from packages.platform_contracts.agent_runtime import AgentRunState, Transition
from packages.platform_contracts.evidence import (
    ApprovalEvidence,
    CancellationEvidence,
    ClarificationEvidence,
    CostEvidence,
    ErrorEvidence,
    EvidenceEnvelope,
    PolicyEvidence,
    ResultEvidence,
    TransitionEvidence,
    fingerprint_payload,
)


class EvidenceBuildError(ValueError):
    """The run cannot be sealed; the message names the inconsistency, never run content."""


def build_evidence_envelope(
    state: AgentRunState,
    transitions: Sequence[Transition | Mapping[str, Any]],
    *,
    validation: ResultValidationReport | None = None,
) -> EvidenceEnvelope:
    if state.status != "terminal" or state.terminal_outcome is None:
        raise EvidenceBuildError("evidence is sealed only for terminal runs")
    history = tuple(_transition(item) for item in transitions)
    if validation is not None:
        recorded = {fp for item in history for fp in item.evidence_fingerprints}
        recorded.update(item.fingerprint for item in state.evidence)
        if validation.fingerprint not in recorded:
            raise EvidenceBuildError("result validation report is not bound to this run's recorded evidence")
    outcome = state.terminal_outcome
    intent = state.intent
    contract = (intent or {}).get("semantic_contract") or {}
    return EvidenceEnvelope.build(
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        request_id=state.request_id,
        purpose=state.purpose,
        graph_version=state.graph_version,
        terminal_kind=outcome.kind,
        context_snapshot_id=state.context_snapshot_id,
        intent_fingerprint=fingerprint_payload(intent) if intent else None,
        semantic_contract=(
            f"{contract['contract_id']}@{contract['contract_version']}"
            if contract.get("contract_id") and contract.get("contract_version")
            else None
        ),
        policy=_policy(state.policy_decision),
        cost=_cost(state.cost_decision),
        approval=_approval(state.approval_state),
        result=_result(validation),
        clarification=_clarification(state.clarification_state),
        cancellation=_cancellation(state),
        errors=tuple(ErrorEvidence(code=e.code, reference=e.message_reference) for e in state.errors),
        transitions=history,
        terminal_summary_reference=outcome.summary_reference,
        terminal_evidence_fingerprints=tuple(item.fingerprint for item in outcome.evidence),
        completed_at=outcome.completed_at,
    )


def _transition(item: Transition | Mapping[str, Any]) -> TransitionEvidence:
    if isinstance(item, Transition):
        return TransitionEvidence(
            sequence=item.sequence,
            from_node=item.from_node,
            to_node=item.to_node,
            to_status=item.to_status,
            evidence_fingerprints=tuple(e.fingerprint for e in item.evidence),
        )
    payload = item.get("evidence_payload") or []
    if isinstance(payload, str):
        payload = json.loads(payload)
    return TransitionEvidence(
        sequence=item["transition_seq"],
        from_node=item["from_node"],
        to_node=item["to_node"],
        to_status=item["to_status"],
        evidence_fingerprints=tuple(e["fingerprint"] for e in payload),
    )


def _policy(decision: dict[str, Any] | None) -> PolicyEvidence | None:
    if not decision:
        return None
    return PolicyEvidence(
        decision_id=decision["decision_id"],
        effect=decision["effect"],
        reasons=tuple(decision["reasons"]),
        policy_version=decision["policy_version"],
        enforced_filter_ids=tuple(decision.get("enforced_filter_ids") or ()),
    )  # policy_values_reference is deliberately dropped


def _cost(decision: dict[str, Any] | None) -> CostEvidence | None:
    if not decision:
        return None
    requires = decision.get("requires_approval")
    return CostEvidence(
        estimated_cost_units=decision.get("estimated_cost_units"),
        requires_approval=None if requires is None else bool(requires),
        reason=decision.get("reason"),
        observed_cost_units=decision.get("observed_cost_units"),
    )


def _approval(approval: dict[str, Any] | None) -> ApprovalEvidence | None:
    if not approval or "state" not in approval:
        return None
    return ApprovalEvidence(
        state=str(approval["state"]),
        review_kind=approval.get("review_kind"),
        review_id=approval.get("review_id"),
        plan_fingerprint=approval.get("plan_fingerprint"),
    )


def _result(report: ResultValidationReport | None) -> ResultEvidence | None:
    if report is None:
        return None
    return ResultEvidence(
        result_fingerprint=report.result_fingerprint,
        plan_fingerprint=report.plan_fingerprint,
        validation_status=report.status,
        validation_fingerprint=report.fingerprint,
        row_count=report.row_count,
        issue_codes=tuple(sorted({issue.code for issue in report.issues})),
    )


def _clarification(clarification: dict[str, Any] | None) -> ClarificationEvidence | None:
    ambiguities = (clarification or {}).get("ambiguities") or []
    if not ambiguities:
        return None
    return ClarificationEvidence(
        ambiguity_codes=tuple(sorted({item["code"] for item in ambiguities})),
        continuation_count=int(clarification.get("continuation_count", 0)),
    )


def _cancellation(state: AgentRunState) -> CancellationEvidence | None:
    request = state.cancellation
    if request is None:
        return None
    return CancellationEvidence(
        requested_by=request.requested_by,
        policy_source=request.policy_source,
        reason_fingerprint=hashlib.sha256(request.reason.encode()).hexdigest(),
        requested_at=request.requested_at,
    )
