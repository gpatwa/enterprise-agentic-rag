"""Graph node that explains a validated result without being able to change it (ADS-043)."""

from __future__ import annotations

import threading

from app.execution.explanation import Explainer, Explanation, ExplanationIntegrityError, explain_result
from app.execution.result_validation import validate_result
from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError
from packages.platform_contracts.analytics_intent import AnalyticalIntent


class ExplanationStore:
    """Process-local, run-scoped explanation handoff; durable storage is a later packet."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[tuple[str, str], Explanation] = {}

    def put(self, tenant_id: str, run_id: str, explanation: Explanation) -> None:
        with self._lock:
            self._items[(tenant_id, run_id)] = explanation

    def get(self, tenant_id: str, run_id: str) -> Explanation:
        with self._lock:
            try:
                return self._items[(tenant_id, run_id)]
            except KeyError as exc:
                raise LookupError("no explanation for this run") from exc


def explain_node(results, contracts, plans, explainer: Explainer, store: ExplanationStore):
    """Explain the stored result. Ungrounded prose degrades to evidence only; it never fails the run.

    `result_validate` is the only legal predecessor and enforced control totals; this node
    re-checks the cheap invariants (shape, grain, truncation) so a tampered or foreign
    result is never narrated.
    """

    def handle(node_input: NodeInput) -> NodeOutput:
        try:
            intent = AnalyticalIntent.model_validate(node_input.payload.get("intent"))
            contract = contracts.get_certified(
                intent.semantic_contract.contract_id, intent.semantic_contract.contract_version
            ).contract
            plan = plans.get(node_input.tenant_id, node_input.run_id, node_input.payload["compiled_plan_reference"])
            result = results.get(node_input.tenant_id, node_input.run_id, node_input.payload["execution_reference"])
        except Exception as exc:  # noqa: BLE001
            return _fail(node_input, "explain_inputs_unavailable", type(exc).__name__)
        report = validate_result(result, plan, intent, contract, require_control_totals=False)
        if not report.acceptable:
            return _fail(node_input, "explain_result_invalid", ",".join(report.blocking_codes))
        try:
            explanation = explain_result(result, intent, contract, explainer)
        except ExplanationIntegrityError:
            return _fail(node_input, "explain_result_mutated", node_input.run_id)
        store.put(node_input.tenant_id, node_input.run_id, explanation)
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="terminal",
            evidence=(
                EvidenceReference(
                    evidence_id=f"explanation:{node_input.run_id}:{explanation.fingerprint[:16]}",
                    kind="decision",
                    fingerprint=explanation.fingerprint,
                ),
            ),
        )

    return handle


def _fail(node_input: NodeInput, code: str, reference: str) -> NodeOutput:
    return NodeOutput(
        run_id=node_input.run_id,
        node_id=node_input.node_id,
        status="failed",
        error=RunError(code=code, message_reference=f"{node_input.run_id}:{reference}"[:255]),
    )
