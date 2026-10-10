from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.platform_contracts.agent_runtime import (
    AgentRunState,
    EvidenceReference,
    NodeOutput,
    RunBudget,
    RunError,
    TerminalOutcome,
    Transition,
    is_legal_transition,
)


def budget() -> RunBudget:
    return RunBudget(deadline=datetime(2030, 1, 1, tzinfo=timezone.utc))


def evidence() -> EvidenceReference:
    return EvidenceReference(evidence_id="ev-1", kind="transition", fingerprint="abc")


def state(**changes: object) -> AgentRunState:
    values: dict[str, object] = {
        "run_id": "run-1",
        "request_id": "request-1",
        "tenant_id": "tenant-1",
        "purpose": "analytics",
        "graph_version": "graph.v1",
        "current_node": "create",
        "context_snapshot_id": "ctx-1",
        "budget": budget(),
    }
    values.update(changes)
    return AgentRunState(**values)


def test_state_round_trips_as_versioned_json() -> None:
    original = state(evidence=(evidence(),), intent={"metric_id": "revenue"})
    restored = AgentRunState.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.schema_version == "v1"


def test_unknown_fields_and_schema_versions_fail_closed() -> None:
    with pytest.raises(ValidationError):
        state(unknown="value")
    with pytest.raises(ValidationError):
        state(schema_version="v2")


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"status": "terminal"}, "terminal state"),
        (
            {
                "status": "active",
                "terminal_outcome": TerminalOutcome(kind="failed", summary_reference="s", evidence=(evidence(),)),
            },
            "terminal_outcome",
        ),
        ({"status": "cancel_requested"}, "cancellation"),
        ({"transition_count": 33}, "transition_count"),
    ],
)
def test_invalid_states_are_rejected(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        state(**changes)


def test_terminal_outcomes_require_evidence_and_failed_output_requires_error() -> None:
    with pytest.raises(ValidationError):
        TerminalOutcome(kind="succeeded", summary_reference="summary", evidence=())
    with pytest.raises(ValidationError, match="requires error"):
        NodeOutput(run_id="run-1", node_id="retrieve", status="failed")


def test_node_output_rejects_illegal_shape_and_accepts_failure_evidence() -> None:
    error = RunError(code="policy_denied", message_reference="err-1", evidence=(evidence(),))
    output = NodeOutput(run_id="run-1", node_id="policy", status="failed", error=error)
    assert output.error == error
    with pytest.raises(ValidationError, match="requires next_node"):
        NodeOutput(run_id="run-1", node_id="policy", status="completed")


def test_transition_contract_rejects_terminal_target_node() -> None:
    with pytest.raises(ValidationError, match="cannot target"):
        Transition(
            run_id="run-1",
            tenant_id="tenant-1",
            graph_version="graph.v1",
            sequence=1,
            from_node="explain",
            to_node="terminal",
            from_status="active",
            to_status="terminal",
            idempotency_key="run-1:1:explain",
        )


def test_transition_contract_rejects_illegal_edge() -> None:
    with pytest.raises(ValidationError, match="illegal transition"):
        Transition(
            run_id="run-1",
            tenant_id="tenant-1",
            graph_version="graph.v1",
            sequence=1,
            from_node="create",
            to_node="execute",
            from_status="active",
            to_status="active",
            idempotency_key="run-1:1:create",
        )


def test_legal_and_illegal_graph_transitions() -> None:
    assert is_legal_transition("create", "bootstrap", "active")
    assert is_legal_transition("policy", None, "terminal")
    assert not is_legal_transition("create", "execute", "active")
    assert not is_legal_transition("explain", "retrieve", "active")
