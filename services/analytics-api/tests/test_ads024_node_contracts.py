import pytest

from app.harness import NodeContractError, NodeContractKit, NodeTimeoutError, TypedNodeError
from packages.platform_contracts.agent_runtime import NodeInput, NodeOutput, RunBudget
from packages.platform_contracts.determinism import DeterministicControls


def node_input(node_id: str, *, cancelled: bool = False) -> NodeInput:
    return NodeInput(
        run_id="run-1", tenant_id="tenant-1", purpose="analytics", node_id=node_id,
        state_version=0, context_snapshot_id="context-1", payload={},
        remaining_budget=RunBudget(deadline=DeterministicControls.from_seed("kit").clock.now()),
        cancellation_requested=cancelled,
    )


def success(node: NodeInput) -> NodeOutput:
    return NodeOutput(run_id=node.run_id, node_id=node.node_id, status="completed", next_node="terminal")


def test_every_registered_node_passes_conformance_suite():
    handlers = {node_id: success for node_id in ("create", "bootstrap", "retrieve")}
    report = NodeContractKit().conformance(handlers, {node_id: node_input(node_id) for node_id in handlers})
    assert report.passed
    report.require_passed()
    assert {result.node_id for result in report.results} == set(handlers)


def test_typed_error_timeout_and_cancellation_are_normalized():
    kit = NodeContractKit()

    def typed_error(node: NodeInput) -> NodeOutput:
        raise TypedNodeError("provider_denied", "error-1")

    def timeout(node: NodeInput) -> NodeOutput:
        raise NodeTimeoutError("slow provider")

    denied = kit.invoke(typed_error, node_input("policy"))
    timed_out = kit.invoke(timeout, node_input("retrieve"))
    cancelled = kit.invoke(success, node_input("retrieve", cancelled=True))
    assert denied.error is not None and denied.error.code == "provider_denied"
    assert timed_out.error is not None and timed_out.error.code == "node_timeout"
    assert timed_out.error.retryable is True
    assert cancelled.status == "cancelled" and cancelled.next_node is None


def test_output_identity_violation_fails_closed():
    def wrong_identity(node: NodeInput) -> NodeOutput:
        return NodeOutput(run_id="other-run", node_id=node.node_id, status="completed", next_node="terminal")

    with pytest.raises(NodeContractError, match="run_id"):
        NodeContractKit().invoke(wrong_identity, node_input("create"))
