"""Graph node that gates execution results before anything may explain them."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any

from app.execution.result_validation import validate_result
from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import SemanticContract

ControlTotals = Callable[[NodeInput, AnalyticalIntent, SemanticContract], Mapping[str, Any]]


def result_validation_node(plans, results, contracts, control_totals: ControlTotals):
    """Validate the stored result against the run's intent, plan, and a control query.

    Any blocking issue (truncation, fanout, missing groups, bad totals, shape or grain
    breaks) fails the run; a failed control query fails closed too. Warnings pass and are
    visible through the evidence fingerprint and the report callers can recompute.
    """

    def handle(node_input: NodeInput) -> NodeOutput:
        try:
            intent = AnalyticalIntent.model_validate(node_input.payload.get("intent"))
            contract = contracts.get_certified(
                intent.semantic_contract.contract_id, intent.semantic_contract.contract_version
            ).contract
            plan = plans.get(node_input.tenant_id, node_input.run_id, node_input.payload["compiled_plan_reference"])
            result = results.get(node_input.tenant_id, node_input.run_id, node_input.payload["execution_reference"])
        except Exception as exc:  # noqa: BLE001 - missing or foreign references never validate.
            return _fail(node_input, "result_inputs_unavailable", type(exc).__name__)
        try:
            totals = control_totals(node_input, intent, contract) if intent.group_by else {}
        except Exception as exc:  # noqa: BLE001 - an unverifiable result is not a valid one.
            return _fail(node_input, "control_query_failed", type(exc).__name__)
        report = validate_result(result, plan, intent, contract, control_totals=totals)
        evidence = (
            EvidenceReference(
                evidence_id=f"result-validation:{node_input.run_id}:{report.fingerprint[:16]}",
                kind="decision",
                fingerprint=report.fingerprint,
            ),
        )
        if not report.acceptable:
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="failed",
                error=RunError(
                    code="result_invalid",
                    message_reference=f"{node_input.run_id}:{','.join(report.blocking_codes)}"[:255],
                ),
                evidence=evidence,
            )
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="explain",
            evidence=evidence,
        )

    return handle


def _fail(node_input: NodeInput, code: str, reference: str) -> NodeOutput:
    fingerprint = hashlib.sha256(f"{code}:{reference}".encode()).hexdigest()
    return NodeOutput(
        run_id=node_input.run_id,
        node_id=node_input.node_id,
        status="failed",
        error=RunError(code=code, message_reference=f"{node_input.run_id}:{reference}"),
        evidence=(
            EvidenceReference(
                evidence_id=f"result-validation:{fingerprint[:32]}", kind="error", fingerprint=fingerprint
            ),
        ),
    )
