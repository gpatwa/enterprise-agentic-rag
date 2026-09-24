"""Lease-fenced graph runner with bounded transitions and deterministic guards."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping

from app.harness.graph import TERMINAL_NODE, GraphNode
from app.harness.node_contracts import NodeContractKit
from app.runtime.control_store import ControlStore, Lease
from packages.platform_contracts.agent_runtime import (
    LEGAL_TRANSITIONS,
    AgentRunState,
    EvidenceReference,
    NodeInput,
    RunError,
    TerminalOutcome,
    Transition,
    is_legal_transition,
)


class GraphRunError(RuntimeError):
    """Raised when the graph cannot safely proceed within its declared budget."""


@dataclass(frozen=True)
class GraphDefinition:
    version: str
    nodes: Mapping[str, GraphNode]
    output_fields: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.version.strip() or not self.nodes:
            raise ValueError("graph definition requires a version and at least one node")
        unknown = set(self.nodes) - set(LEGAL_TRANSITIONS)
        if unknown:
            raise ValueError(f"graph definition contains unknown node: {sorted(unknown)[0]}")
        missing_targets = {
            target
            for node_id in self.nodes
            for target in LEGAL_TRANSITIONS[node_id]
            if target != "terminal" and target not in self.nodes
        }
        if missing_targets:
            raise ValueError(f"graph definition is missing allowlisted node: {sorted(missing_targets)[0]}")
        if set(self.output_fields) - set(self.nodes):
            raise ValueError("node output declarations contain an unregistered node")
        unsupported_fields = {
            name for names in self.output_fields.values() for name in names
            if name not in {"intent", "policy_decision", "cost_decision", "approval_state", "compiled_plan_reference", "execution_reference"}
        }
        if unsupported_fields:
            raise ValueError(f"node output field is not writable: {sorted(unsupported_fields)[0]}")


@dataclass(frozen=True)
class GraphRunResult:
    state: AgentRunState
    lease: Lease
    transitions: tuple[Transition, ...]


class AgentGraphRunner:
    """Execute registered handlers while persisting each transition atomically."""

    def __init__(
        self,
        store: ControlStore,
        graph: GraphDefinition,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        node_contracts: NodeContractKit | None = None,
    ) -> None:
        self.store = store
        self.graph = graph
        self.now = now
        self.node_contracts = node_contracts or NodeContractKit()

    def start(
        self,
        state: AgentRunState,
        *,
        owner_id: str,
        lease_token: str,
    ) -> GraphRunResult:
        if state.graph_version != self.graph.version:
            raise GraphRunError("run graph version does not match registered graph")
        if state.status == "terminal" or state.transition_count >= state.budget.max_transitions:
            raise GraphRunError("new run must be active with transition budget remaining")
        self.store.create_run(state)
        lease = self.store.acquire_lease(
            run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose,
            owner_id=owner_id, lease_token=lease_token, now=self.now(),
        )
        return self._execute(state, lease)

    def resume(
        self,
        *,
        run_id: str,
        tenant_id: str,
        purpose: str,
        owner_id: str,
        lease_token: str,
    ) -> GraphRunResult:
        lease = self.store.acquire_lease(
            run_id=run_id, tenant_id=tenant_id, purpose=purpose,
            owner_id=owner_id, lease_token=lease_token, now=self.now(),
        )
        state = self.store.load_latest_checkpoint(run_id=run_id, tenant_id=tenant_id, purpose=purpose)
        if state.graph_version != self.graph.version:
            raise GraphRunError("checkpoint graph version does not match registered graph")
        return self._execute(state, lease)

    def _execute(self, state: AgentRunState, lease: Lease) -> GraphRunResult:
        transitions: list[Transition] = []
        fingerprints: set[str] = set()
        previous_cost = state.cost_decision or {}
        cost_units = float(previous_cost.get("observed_cost_units", 0.0)) if isinstance(previous_cost, dict) else 0.0
        while state.status != "terminal":
            if self.store.cancellation_requested(
                run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose
            ):
                state = self.store.load_run_state(
                    run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose
                )
                if state.cancellation is None:
                    raise GraphRunError("cancel flag exists without a typed cancellation request")
                state, transition = self._terminalize(state, lease, "cancelled", "run_cancelled", cost_units=cost_units)
                transitions.append(transition)
                break
            now = self.now()
            if now >= state.budget.deadline:
                state, transition = self._terminalize(state, lease, "failed", "run_deadline_exceeded")
                transitions.append(transition)
                break
            if state.transition_count >= state.budget.max_transitions:
                state, transition = self._terminalize(state, lease, "failed", "transition_budget_exceeded")
                transitions.append(transition)
                break
            handler = self.graph.nodes.get(state.current_node)
            if handler is None:
                state, transition = self._terminalize(state, lease, "failed", "unregistered_node")
                transitions.append(transition)
                break
            node_input = NodeInput(
                run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose,
                node_id=state.current_node, state_version=state.transition_count,
                context_snapshot_id=state.context_snapshot_id, payload=self._payload(state),
                remaining_budget=state.budget,
            )
            fingerprint = _state_fingerprint(node_input)
            if fingerprint in fingerprints:
                state, transition = self._terminalize(state, lease, "failed", "cycle_detected")
                transitions.append(transition)
                break
            fingerprints.add(fingerprint)
            try:
                output = self.node_contracts.invoke(handler, node_input)
            except Exception as exc:  # noqa: BLE001 - unknown node failures become bounded terminal evidence.
                output = self.node_contracts.error_output(
                    node_input,
                    self._typed_error("node_exception", type(exc).__name__),
                )
            node_cost = output.payload.get("cost_units", 0)
            if not isinstance(node_cost, (int, float)) or node_cost < 0:
                output = self.node_contracts.error_output(
                    node_input, self._typed_error("invalid_cost_observation", state.current_node)
                )
                node_cost = 0
            cost_units += float(node_cost)
            if cost_units > state.budget.max_cost_units:
                state, transition = self._terminalize(state, lease, "failed", "cost_budget_exceeded", cost_units=cost_units)
                transitions.append(transition)
                break
            if output.status == "waiting":
                state, transition = self._terminalize(state, lease, "review_required", "approval_pause_not_enabled", cost_units=cost_units)
                transitions.append(transition)
                break
            if output.status == "completed" and output.next_node == TERMINAL_NODE and state.current_node not in {
                "policy", "estimate", "approve", "result_validate", "explain"
            }:
                state, transition = self._terminalize(state, lease, "failed", "illegal_success_terminal", cost_units=cost_units)
                transitions.append(transition)
                break
            next_node, terminal_kind, error = self._interpret(output.status, output.error, state.current_node, output.next_node)
            if terminal_kind is None and (next_node is None or not is_legal_transition(state.current_node, next_node, "active")):
                state, transition = self._terminalize(state, lease, "failed", "illegal_transition", cost_units=cost_units)
                transitions.append(transition)
                break
            patch, patch_error = self._state_patch(state, output.payload)
            if patch_error:
                state, transition = self._terminalize(state, lease, "failed", patch_error, cost_units=cost_units)
                transitions.append(transition)
                break
            state, transition = self._commit_step(
                state, lease, next_node=next_node, terminal_kind=terminal_kind,
                error=error, output_evidence=output.evidence, cost_units=cost_units, state_patch=patch,
            )
            transitions.append(transition)
        return GraphRunResult(state=state, lease=lease, transitions=tuple(transitions))

    @staticmethod
    def _payload(state: AgentRunState) -> dict:
        return {
            "intent": state.intent,
            "policy_decision": state.policy_decision,
            "cost_decision": state.cost_decision,
            "approval_state": state.approval_state,
            "compiled_plan_reference": state.compiled_plan_reference,
            "execution_reference": state.execution_reference,
        }

    @staticmethod
    def _interpret(status: str, error: RunError | None, node_id: str, next_node: str | None):
        if status == "cancelled":
            return None, "cancelled", None
        if status == "failed":
            code = error.code if error else "node_failed"
            kind = "refused" if code == "policy_denied" else "review_required" if code == "stale_context" else "failed"
            return None, kind, error
        if next_node == TERMINAL_NODE:
            return None, "succeeded", None
        if next_node is None:
            return None, "failed", RunError(code="missing_target", message_reference=f"{node_id}:missing-target")
        return next_node, None, None

    def _commit_step(
        self,
        state: AgentRunState,
        lease: Lease,
        *,
        next_node: str | None,
        terminal_kind: str | None,
        error: RunError | None,
        output_evidence: tuple[EvidenceReference, ...],
        cost_units: float | None = None,
        state_patch: dict | None = None,
    ) -> tuple[AgentRunState, Transition]:
        sequence = state.transition_count + 1
        if terminal_kind is None and sequence >= state.budget.max_transitions:
            next_node = None
            terminal_kind = "failed"
            error = RunError(
                code="transition_budget_exceeded",
                message_reference=f"{state.run_id}:transition-budget-exceeded",
            )
        evidence = self._evidence(state, sequence, "graph_step", f"{state.current_node}:{next_node or terminal_kind}")
        combined_evidence = tuple((*output_evidence, *evidence))
        cost_decision = (state_patch or {}).get("cost_decision", state.cost_decision)
        if cost_units is not None:
            cost_decision = {**(cost_decision or {}), "observed_cost_units": cost_units}
        if terminal_kind is None:
            next_state = AgentRunState.model_validate({
                **state.model_dump(mode="python"),
                **(state_patch or {}),
                "current_node": next_node, "transition_count": sequence,
                        "evidence": (*state.evidence, *combined_evidence),
                "cost_decision": cost_decision,
            })
            to_status = "active"
        else:
            outcome = TerminalOutcome(
                kind=terminal_kind, summary_reference=f"{state.run_id}:terminal",
                evidence=combined_evidence, completed_at=self.now(),
            )
            errors = (*state.errors, error) if error else state.errors
            next_state = AgentRunState.model_validate({
                **state.model_dump(mode="python"),
                **(state_patch or {}),
                "status": "terminal", "transition_count": sequence,
                        "terminal_outcome": outcome, "evidence": (*state.evidence, *combined_evidence),
                        "errors": errors,
                "cost_decision": cost_decision,
            })
            to_status = "terminal"
        transition = Transition(
            run_id=state.run_id, tenant_id=state.tenant_id, graph_version=state.graph_version,
            sequence=sequence, from_node=state.current_node, to_node=next_node,
            from_status=state.status, to_status=to_status,
            idempotency_key=f"{state.run_id}:{sequence}:{state.current_node}", evidence=combined_evidence,
        )
        self.store.commit_transition(next_state, transition, fencing_seq=lease.fencing_seq)
        return next_state, transition

    def _terminalize(
        self, state: AgentRunState, lease: Lease, kind: str, code: str, *, cost_units: float | None = None
    ) -> tuple[AgentRunState, Transition]:
        error = None if kind == "cancelled" else RunError(code=code, message_reference=f"{state.run_id}:{code}")
        return self._commit_step(
            state, lease, next_node=None, terminal_kind=kind, error=error, output_evidence=(), cost_units=cost_units
        )

    def _state_patch(self, state: AgentRunState, payload: dict) -> tuple[dict, str | None]:
        observed = set(payload) - {"cost_units"}
        declared = self.graph.output_fields.get(state.current_node, frozenset())
        undeclared = observed - declared
        if undeclared:
            return {}, "undeclared_node_output"
        patch = {name: payload[name] for name in observed}
        try:
            AgentRunState.model_validate({**state.model_dump(mode="python"), **patch})
        except Exception:
            return {}, "invalid_node_state_patch"
        return patch, None

    def _evidence(self, state: AgentRunState, sequence: int, kind: str, payload: str) -> tuple[EvidenceReference, ...]:
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        return (EvidenceReference(
            evidence_id=f"{state.run_id}:transition:{sequence}", kind="transition", fingerprint=fingerprint,
        ),)

    @staticmethod
    def _typed_error(code: str, reference: str):
        from app.harness.node_contracts import TypedNodeError

        return TypedNodeError(code=code, message_reference=reference)


def _state_fingerprint(node_input: NodeInput) -> str:
    payload = node_input.model_dump(mode="json")
    payload.pop("remaining_budget", None)
    payload.pop("state_version", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
