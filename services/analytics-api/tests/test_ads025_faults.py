import pytest

from app.harness import TERMINAL_NODE, FaultPlan, GraphHarness
from packages.platform_contracts.agent_runtime import NodeInput, NodeOutput
from packages.platform_contracts.determinism import DeterministicControls
from packages.platform_contracts.harness import ExpectedTrace, ExpectedTraceStep, HarnessScenario

NODES = ("create", "bootstrap", "retrieve", "resolve", "plan", "validate", "compile", "policy")


def handlers():
    targets = dict(zip(NODES, NODES[1:] + (TERMINAL_NODE,)))

    def make(node_id: str):
        def run(node: NodeInput) -> NodeOutput:
            return NodeOutput(run_id=node.run_id, node_id=node_id, status="completed", next_node=targets[node_id])

        return run

    return {node_id: make(node_id) for node_id in NODES}


def scenario(node_id: str, terminal_kind: str) -> HarnessScenario:
    steps = []
    for sequence, current in enumerate(NODES[: NODES.index(node_id)], start=1):
        steps.append(ExpectedTraceStep(sequence=sequence, from_node=current, to_node=NODES[sequence], to_status="active"))
    steps.append(ExpectedTraceStep(sequence=len(steps) + 1, from_node=node_id, to_node=None, to_status="terminal"))
    return HarnessScenario.build(
        scenario_id=f"fault-{node_id}", tenant_id="tenant-1", purpose="analytics",
        request="Show revenue", context_snapshot_id="context-1", graph_version="graph-v1",
        expected_trace=ExpectedTrace(graph_version="graph-v1", steps=tuple(steps), terminal_kind=terminal_kind),
    )


@pytest.mark.parametrize(
    ("node_id", "plan", "terminal_kind"),
    [
        ("retrieve", FaultPlan().stale_context("retrieve"), "review_required"),
        ("resolve", FaultPlan().timeout("resolve"), "failed"),
        ("policy", FaultPlan().denial("policy"), "refused"),
        ("plan", FaultPlan().crash("plan"), "failed"),
        ("resolve", FaultPlan().malformed_model_output("resolve"), "failed"),
    ],
)
def test_each_fault_reaches_bounded_terminal_state(node_id, plan, terminal_kind):
    result = GraphHarness(plan.apply(handlers())).run(
        scenario(node_id, terminal_kind), DeterministicControls.from_seed(f"fault-{node_id}")
    )
    assert result.state.status == "terminal"
    assert result.state.terminal_outcome is not None
    assert result.state.terminal_outcome.kind == terminal_kind


def test_fault_plan_rejects_duplicate_node_registration():
    with pytest.raises(ValueError, match="already registered"):
        FaultPlan().timeout("retrieve").denial("retrieve")

    with pytest.raises(ValueError, match="unregistered node"):
        FaultPlan().timeout("missing").apply(handlers())
