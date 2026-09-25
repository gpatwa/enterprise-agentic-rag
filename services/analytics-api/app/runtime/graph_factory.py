"""Canonical v2 graph wiring and typed state-write declarations."""

from __future__ import annotations

from collections.abc import Mapping

from app.harness.graph import GraphNode
from app.runtime.graph_runner import GraphDefinition
from packages.platform_contracts.agent_runtime import TRANSITIONS_BY_VERSION

GOVERNED_V2_OUTPUT_FIELDS = {
    "bootstrap": frozenset({"request_text"}),
    "retrieve": frozenset({"context_pack"}),
    "extract_intent": frozenset({"intent"}),
    "resolve": frozenset({"intent", "clarification_state", "approval_state"}),
    "clarify": frozenset({"intent", "clarification_state"}),
    "validate": frozenset({"intent", "approval_state"}),
    "compile": frozenset({"compiled_plan_reference"}),
    "policy": frozenset({"policy_decision", "approval_state"}),
    "estimate": frozenset({"cost_decision", "approval_state"}),
    "approve": frozenset({"approval_state"}),
    "execute": frozenset({"execution_reference"}),
}


def governed_graph_v2(nodes: Mapping[str, GraphNode]) -> GraphDefinition:
    required = set(TRANSITIONS_BY_VERSION["graph-v2"])
    missing = required - set(nodes)
    extra = set(nodes) - required
    if missing or extra:
        raise ValueError(f"graph-v2 node registry mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    return GraphDefinition(
        version="graph-v2",
        nodes=dict(nodes),
        output_fields=GOVERNED_V2_OUTPUT_FIELDS,
    )
