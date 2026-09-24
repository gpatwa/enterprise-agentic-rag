import pytest

from app.harness import TERMINAL_NODE, GraphHarness, GraphHarnessError
from packages.platform_contracts.agent_runtime import NodeInput, NodeOutput
from packages.platform_contracts.determinism import DeterministicControls
from packages.platform_contracts.harness import ExpectedTrace, ExpectedTraceStep, HarnessScenario

NODES = ("create", "bootstrap", "retrieve", "resolve", "plan", "validate", "compile", "policy")


def trace(*, policy_target: str | None = None, terminal_kind: str = "succeeded") -> ExpectedTrace:
    steps = [
        ExpectedTraceStep(sequence=1, from_node="create", to_node="bootstrap", to_status="active"),
        ExpectedTraceStep(sequence=2, from_node="bootstrap", to_node="retrieve", to_status="active"),
        ExpectedTraceStep(sequence=3, from_node="retrieve", to_node="resolve", to_status="active"),
        ExpectedTraceStep(sequence=4, from_node="resolve", to_node="plan", to_status="active"),
        ExpectedTraceStep(sequence=5, from_node="plan", to_node="validate", to_status="active"),
        ExpectedTraceStep(sequence=6, from_node="validate", to_node="compile", to_status="active"),
        ExpectedTraceStep(sequence=7, from_node="compile", to_node="policy", to_status="active"),
    ]
    if policy_target is None:
        steps.append(ExpectedTraceStep(sequence=8, from_node="policy", to_node=None, to_status="terminal"))
    else:
        steps.append(ExpectedTraceStep(sequence=8, from_node="policy", to_node=policy_target, to_status="active"))
        steps.append(ExpectedTraceStep(sequence=9, from_node=policy_target, to_node=None, to_status="terminal"))
    return ExpectedTrace(graph_version="graph-v1", steps=tuple(steps), terminal_kind=terminal_kind)


def scenario(expected_trace: ExpectedTrace) -> HarnessScenario:
    return HarnessScenario.build(
        scenario_id="ads023-happy-path", tenant_id="demo", purpose="analytics",
        request="Show revenue by month", context_snapshot_id="snapshot-1",
        graph_version="graph-v1", expected_trace=expected_trace, inputs={"dataset": "orders"},
    )


def handlers(*, policy_target: str = TERMINAL_NODE, cycle: bool = False):
    targets = dict(zip(NODES, NODES[1:] + (policy_target,)))
    if cycle:
        targets["retrieve"] = "bootstrap"
    if policy_target != TERMINAL_NODE:
        targets[policy_target] = TERMINAL_NODE

    def make(node_id: str):
        def run(node: NodeInput) -> NodeOutput:
            target = targets[node_id]
            return NodeOutput(
                run_id=node.run_id, node_id=node_id, status="completed",
                payload=node.payload, next_node=target,
            )

        return run

    node_ids = NODES if policy_target == TERMINAL_NODE else (*NODES, policy_target)
    return {node_id: make(node_id) for node_id in node_ids}


def test_graph_harness_executes_and_audits_expected_trace():
    result = GraphHarness(handlers()).run(scenario(trace()), DeterministicControls.from_seed("ads023"))
    assert result.state.status == "terminal"
    assert result.state.terminal_outcome is not None
    assert result.state.terminal_outcome.kind == "succeeded"
    assert len(result.transitions) == 8
    assert result.transitions[-1].to_node is None
    assert result.transitions[-1].to_status == "terminal"


@pytest.mark.parametrize(
    ("expected_trace", "node_handlers", "message"),
    [
        (trace(policy_target="estimate"), handlers(), "missing transition"),
        (trace(), handlers(policy_target="estimate"), "extra transition"),
    ],
)
def test_missing_and_extra_transitions_fail_independently(expected_trace, node_handlers, message):
    with pytest.raises(GraphHarnessError, match=message):
        GraphHarness(node_handlers).run(scenario(expected_trace), DeterministicControls.from_seed("ads023"))


def test_cycle_is_rejected_before_it_can_repeat():
    with pytest.raises(GraphHarnessError, match="cycle detected"):
        GraphHarness(handlers(cycle=True)).run(scenario(trace()), DeterministicControls.from_seed("ads023"))


def test_illegal_edge_is_rejected_by_transition_contract():
    node_handlers = handlers()

    def illegal(node: NodeInput) -> NodeOutput:
        return NodeOutput(run_id=node.run_id, node_id=node.node_id, status="completed", next_node="execute")

    node_handlers["create"] = illegal
    with pytest.raises(GraphHarnessError, match="illegal transition"):
        GraphHarness(node_handlers).run(scenario(trace()), DeterministicControls.from_seed("ads023"))


def test_successful_terminal_signal_is_restricted_to_terminal_capable_nodes():
    node_handlers = handlers()

    def premature_success(node: NodeInput) -> NodeOutput:
        return NodeOutput(run_id=node.run_id, node_id=node.node_id, status="completed", next_node=TERMINAL_NODE)

    node_handlers["create"] = premature_success
    with pytest.raises(GraphHarnessError, match="successful terminal"):
        GraphHarness(node_handlers).run(scenario(trace()), DeterministicControls.from_seed("ads023"))


def test_terminal_kind_and_transition_budget_are_asserted():
    with pytest.raises(GraphHarnessError, match="terminal outcome mismatch"):
        GraphHarness(handlers()).run(
            scenario(trace(terminal_kind="failed")), DeterministicControls.from_seed("ads023")
        )

    with pytest.raises(GraphHarnessError, match="transition budget"):
        GraphHarness(handlers(), max_transitions=1).run(
            scenario(trace()), DeterministicControls.from_seed("ads023")
        )
