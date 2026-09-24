import pytest

from app.harness import TERMINAL_NODE, CapturedTrace, GraphHarness, TraceReplayError
from packages.platform_contracts.agent_runtime import NodeInput, NodeOutput
from packages.platform_contracts.determinism import DeterministicControls
from packages.platform_contracts.harness import ExpectedTrace, ExpectedTraceStep, HarnessScenario

NODES = ("create", "bootstrap", "retrieve", "resolve", "plan", "validate", "compile", "policy")


def handlers():
    targets = dict(zip(NODES, NODES[1:] + (TERMINAL_NODE,)))

    def make(node_id: str):
        def run(node: NodeInput) -> NodeOutput:
            return NodeOutput(run_id=node.run_id, node_id=node_id, status="completed", payload=node.payload, next_node=targets[node_id])

        return run

    return {node_id: make(node_id) for node_id in NODES}


def scenario(request: str = "Show revenue") -> HarnessScenario:
    steps = tuple(
        ExpectedTraceStep(sequence=index, from_node=current, to_node=next_node, to_status="active")
        for index, (current, next_node) in enumerate(zip(NODES, NODES[1:]), start=1)
    ) + (ExpectedTraceStep(sequence=8, from_node="policy", to_node=None, to_status="terminal"),)
    return HarnessScenario.build(
        scenario_id="ads026-trace", tenant_id="tenant-1", purpose="analytics",
        request=request, context_snapshot_id="context-1", graph_version="graph-v1",
        expected_trace=ExpectedTrace(graph_version="graph-v1", steps=steps, terminal_kind="succeeded"),
        inputs={"api_key": "secret", "nested": {"token": "secret-token"}},
    )


def test_trace_is_redacted_exportable_and_replays_without_live_dependencies(tmp_path):
    fixture = scenario()
    result = GraphHarness(handlers()).run(fixture, DeterministicControls.from_seed("ads026"))
    captured = CapturedTrace.capture(fixture, result)
    assert captured.redacted_payload == {"api_key": "[REDACTED]", "nested": {"token": "[REDACTED]"}}

    path = tmp_path / "trace.json"
    captured.export_json(path)
    restored = CapturedTrace.load_json(path)
    replayed = restored.replay(fixture, GraphHarness(handlers()), DeterministicControls.from_seed("ads026"))
    assert replayed.transitions == result.transitions


def test_trace_replay_rejects_a_different_fixture():
    fixture = scenario()
    result = GraphHarness(handlers()).run(fixture, DeterministicControls.from_seed("ads026"))
    captured = CapturedTrace.capture(fixture, result)
    changed = scenario("Show cost")
    with pytest.raises(TraceReplayError, match="fixture digest"):
        captured.replay(changed, GraphHarness(handlers()), DeterministicControls.from_seed("ads026"))
