"""Bounded fault-injection DSL for deterministic graph scenarios."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from app.harness.node_contracts import GraphNode
from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError

FaultKind = Literal["stale_context", "timeout", "denial", "crash", "malformed_model_output"]


@dataclass(frozen=True)
class FaultSpec:
    node_id: str
    kind: FaultKind
    message_reference: str


class FaultPlan:
    """Compose at most one deterministic fault per node."""

    _CODES: dict[FaultKind, str] = {
        "stale_context": "stale_context",
        "timeout": "node_timeout",
        "denial": "policy_denied",
        "crash": "node_crash",
        "malformed_model_output": "malformed_model_output",
    }

    def __init__(self, specs: tuple[FaultSpec, ...] = ()):
        self.specs = specs

    def add(self, node_id: str, kind: FaultKind, *, message_reference: str | None = None) -> "FaultPlan":
        if any(spec.node_id == node_id for spec in self.specs):
            raise ValueError(f"fault already registered for node: {node_id}")
        reference = message_reference or f"fault:{node_id}:{kind}"
        return FaultPlan(self.specs + (FaultSpec(node_id, kind, reference),))

    def stale_context(self, node_id: str) -> "FaultPlan":
        return self.add(node_id, "stale_context")

    def timeout(self, node_id: str) -> "FaultPlan":
        return self.add(node_id, "timeout")

    def denial(self, node_id: str) -> "FaultPlan":
        return self.add(node_id, "denial")

    def crash(self, node_id: str) -> "FaultPlan":
        return self.add(node_id, "crash")

    def malformed_model_output(self, node_id: str) -> "FaultPlan":
        return self.add(node_id, "malformed_model_output")

    def apply(self, handlers: Mapping[str, GraphNode]) -> dict[str, GraphNode]:
        by_node = {spec.node_id: spec for spec in self.specs}
        missing = sorted(set(by_node) - set(handlers))
        if missing:
            raise ValueError(f"fault targets unregistered node: {missing[0]}")
        wrapped: dict[str, GraphNode] = {}
        for node_id, handler in handlers.items():
            spec = by_node.get(node_id)
            if spec is None:
                wrapped[node_id] = handler
                continue

            def run(node: NodeInput, *, original=handler, fault=spec) -> NodeOutput:
                return self._fault_output(node, fault) if fault.node_id == node.node_id else original(node)

            wrapped[node_id] = run
        return wrapped

    def _fault_output(self, node: NodeInput, spec: FaultSpec) -> NodeOutput:
        code = self._CODES[spec.kind]
        return NodeOutput(
            run_id=node.run_id,
            node_id=node.node_id,
            status="failed",
            error=RunError(
                code=code,
                message_reference=spec.message_reference,
                retryable=spec.kind == "timeout",
                evidence=(
                    EvidenceReference(
                        evidence_id=f"fault:{node.run_id}:{node.node_id}",
                        kind="error",
                        fingerprint=f"{code}:{spec.message_reference}",
                    ),
                ),
            ),
        )
