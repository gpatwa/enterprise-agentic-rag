"""Deterministic graph execution harness for versioned local scenarios."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from app.harness.node_contracts import NodeContractKit
from packages.platform_contracts.agent_runtime import (
    AgentRunState,
    EvidenceReference,
    NodeInput,
    NodeOutput,
    RunBudget,
    TerminalOutcome,
    Transition,
)
from packages.platform_contracts.determinism import DeterministicControls
from packages.platform_contracts.harness import ExpectedTraceStep, HarnessScenario

TERMINAL_NODE = "terminal"
SUCCESS_TERMINAL_NODES = frozenset({"policy", "estimate", "approve", "result_validate", "explain"})
GraphNode = Callable[[NodeInput], NodeOutput]


class GraphHarnessError(RuntimeError):
    """Raised when a scenario cannot produce its declared bounded trace."""


@dataclass(frozen=True)
class GraphExecutionResult:
    scenario_id: str
    run_id: str
    graph_version: str
    state: AgentRunState
    transitions: tuple[Transition, ...]
    final_payload: dict[str, object]


class GraphHarness:
    """Execute a small authored graph without live models, tools, or storage."""

    def __init__(self, nodes: dict[str, GraphNode], *, deadline_minutes: int = 5, max_transitions: int | None = None):
        self.nodes = dict(nodes)
        self.deadline_minutes = deadline_minutes
        self.max_transitions = max_transitions
        self.node_contracts = NodeContractKit()

    def run(self, scenario: HarnessScenario, controls: DeterministicControls) -> GraphExecutionResult:
        if scenario.graph_version != "graph-v1":
            raise GraphHarnessError(f"unsupported graph version: {scenario.graph_version}")
        run_id = controls.ids.next("run")
        now = controls.clock.now()
        state = AgentRunState(
            run_id=run_id,
            request_id=scenario.scenario_id,
            tenant_id=scenario.tenant_id,
            purpose=scenario.purpose,
            graph_version=scenario.graph_version,
            current_node="create",
            context_snapshot_id=scenario.context_snapshot_id,
            budget=RunBudget(
                deadline=now + timedelta(minutes=self.deadline_minutes),
                max_transitions=self.max_transitions or max(32, len(scenario.expected_trace.steps)),
                max_cost_units=controls.budget.max_cost_units,
            ),
        )
        transitions: list[Transition] = []
        visited = {state.current_node}
        payload = dict(scenario.inputs)

        while state.status != "terminal":
            if len(transitions) >= state.budget.max_transitions:
                raise GraphHarnessError("transition budget exhausted before terminal state")
            node_id = state.current_node
            handler = self.nodes.get(node_id)
            if handler is None:
                raise GraphHarnessError(f"node is not registered: {node_id}")
            node_input = NodeInput(
                run_id=state.run_id,
                tenant_id=state.tenant_id,
                purpose=state.purpose,
                request_id=state.request_id,
                request_text=state.request_text,
                node_id=node_id,
                state_version=state.transition_count,
                context_snapshot_id=state.context_snapshot_id,
                payload=payload,
                remaining_budget=state.budget,
            )
            try:
                output = self.node_contracts.invoke(handler, node_input)
            except Exception as exc:  # noqa: BLE001 - the harness must fail closed.
                raise GraphHarnessError(f"node {node_id} raised {type(exc).__name__}") from exc
            self._validate_output(output, state)
            target, to_status, terminal_kind = self._interpret_output(output, node_id)
            if target is not None and target in visited:
                raise GraphHarnessError(f"cycle detected at node {target}")

            sequence = len(transitions) + 1
            evidence = (
                EvidenceReference(
                    evidence_id=controls.ids.next("transition"),
                    kind="transition",
                    fingerprint=f"{scenario.scenario_id}:{sequence}:{node_id}:{target or to_status}",
                ),
            )
            try:
                transition = Transition(
                    run_id=state.run_id,
                    tenant_id=state.tenant_id,
                    graph_version=state.graph_version,
                    sequence=sequence,
                    from_node=node_id,
                    to_node=target,
                    from_status=state.status,
                    to_status=to_status,
                    idempotency_key=f"{state.run_id}:{sequence}:{node_id}",
                    evidence=evidence,
                )
            except Exception as exc:  # noqa: BLE001 - convert contract failure to harness evidence.
                raise GraphHarnessError(f"transition rejected: {exc}") from exc
            transitions.append(transition)
            if to_status == "terminal":
                outcome = TerminalOutcome(
                    kind=terminal_kind,
                    summary_reference=f"{scenario.scenario_id}:terminal",
                    evidence=evidence,
                    completed_at=controls.clock.now(),
                )
                state = state.model_copy(
                    update={
                        "status": "terminal",
                        "transition_count": sequence,
                        "terminal_outcome": outcome,
                    }
                )
            else:
                assert target is not None
                state = state.model_copy(
                    update={
                        "current_node": target,
                        "transition_count": sequence,
                    }
                )
                visited.add(target)
                payload = dict(output.payload)

        self._assert_expected_trace(scenario, transitions, state)
        return GraphExecutionResult(
            scenario_id=scenario.scenario_id,
            run_id=state.run_id,
            graph_version=state.graph_version,
            state=state,
            transitions=tuple(transitions),
            final_payload=payload,
        )

    @staticmethod
    def _validate_output(output: NodeOutput, state: AgentRunState) -> None:
        if output.run_id != state.run_id:
            raise GraphHarnessError("node output run_id does not match active run")
        if output.node_id != state.current_node:
            raise GraphHarnessError("node output node_id does not match active node")
        if output.status == "waiting":
            raise GraphHarnessError("waiting node outputs are deferred to the approval harness")

    @staticmethod
    def _interpret_output(output: NodeOutput, node_id: str) -> tuple[str | None, str, str]:
        if output.status == "completed":
            if output.next_node == TERMINAL_NODE:
                if node_id not in SUCCESS_TERMINAL_NODES:
                    raise GraphHarnessError(f"successful terminal is not legal from node {node_id}")
                return None, "terminal", "succeeded"
            assert output.next_node is not None
            return output.next_node, "active", "succeeded"
        if output.status == "cancelled":
            return None, "terminal", "cancelled"
        if output.status == "failed":
            code = output.error.code if output.error else "node_failed"
            terminal_kind = "refused" if code == "policy_denied" else "review_required" if code == "stale_context" else "failed"
            return None, "terminal", terminal_kind
        raise GraphHarnessError(f"unsupported node output status: {output.status}")

    @staticmethod
    def _assert_expected_trace(
        scenario: HarnessScenario, actual: list[Transition], state: AgentRunState
    ) -> None:
        expected = scenario.expected_trace.steps
        common = min(len(actual), len(expected))
        for index in range(common):
            observed = actual[index]
            declared = expected[index]
            if not _matches(observed, declared):
                if observed.to_status == "terminal" and declared.to_status != "terminal":
                    raise GraphHarnessError(
                        f"missing transition at sequence {declared.sequence}: "
                        f"expected {declared.from_node}->{declared.to_node or declared.to_status}"
                    )
                if observed.to_status != "terminal" and declared.to_status == "terminal":
                    raise GraphHarnessError(f"extra transition at sequence {declared.sequence}")
                raise GraphHarnessError(
                    f"trace mismatch at sequence {declared.sequence}: "
                    f"expected {declared.from_node}->{declared.to_node or declared.to_status}, "
                    f"observed {observed.from_node}->{observed.to_node or observed.to_status}"
                )
        if len(actual) < len(expected):
            raise GraphHarnessError(
                f"missing transition at sequence {len(actual) + 1}: "
                f"expected {expected[len(actual)].from_node}->{expected[len(actual)].to_node or expected[len(actual)].to_status}"
            )
        if len(actual) > len(expected):
            raise GraphHarnessError(f"extra transition at sequence {len(expected) + 1}")
        outcome = state.terminal_outcome
        if outcome is None or outcome.kind != scenario.expected_trace.terminal_kind:
            observed_kind = outcome.kind if outcome else "none"
            raise GraphHarnessError(
                f"terminal outcome mismatch: expected {scenario.expected_trace.terminal_kind}, observed {observed_kind}"
            )


def _matches(observed: Transition, declared: ExpectedTraceStep) -> bool:
    return (
        observed.sequence == declared.sequence
        and observed.from_node == declared.from_node
        and observed.to_node == declared.to_node
        and observed.to_status == declared.to_status
    )
