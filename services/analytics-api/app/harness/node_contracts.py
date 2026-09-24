"""Node boundary normalization and conformance checks for local harnesses."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError

GraphNode = Callable[[NodeInput], NodeOutput]


class NodeContractError(RuntimeError):
    """Raised when a node violates the typed execution boundary."""


class NodeTimeoutError(TimeoutError):
    """Typed signal that a node exceeded its bounded execution time."""


@dataclass(frozen=True)
class TypedNodeError(RuntimeError):
    """Typed, redacted node failure suitable for a terminal outcome."""

    code: str
    message_reference: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.code


@dataclass(frozen=True)
class NodeConformanceResult:
    node_id: str
    passed: bool
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class NodeConformanceReport:
    results: tuple[NodeConformanceResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    def require_passed(self) -> None:
        failures = [f"{result.node_id}: {failure}" for result in self.results for failure in result.failures]
        if failures:
            raise NodeContractError("; ".join(failures))


class NodeContractKit:
    """Normalize typed errors and run the shared node conformance suite."""

    def invoke(self, handler: GraphNode, node_input: NodeInput) -> NodeOutput:
        if node_input.cancellation_requested:
            return self.cancellation_output(node_input)
        try:
            output = handler(node_input)
        except (NodeTimeoutError, TimeoutError) as exc:
            return self.timeout_output(node_input, str(exc) or "timeout")
        except TypedNodeError as exc:
            return self.error_output(node_input, exc)
        self.validate_output(output, node_input)
        return output

    @staticmethod
    def validate_output(output: NodeOutput, node_input: NodeInput) -> None:
        if output.run_id != node_input.run_id:
            raise NodeContractError("node output run_id does not match input")
        if output.node_id != node_input.node_id:
            raise NodeContractError("node output node_id does not match input")

    @staticmethod
    def error_output(node_input: NodeInput, error: TypedNodeError) -> NodeOutput:
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="failed",
            error=RunError(
                code=error.code,
                message_reference=error.message_reference,
                retryable=error.retryable,
                evidence=(
                    EvidenceReference(
                        evidence_id=f"{node_input.run_id}:{node_input.node_id}:error",
                        kind="error",
                        fingerprint=f"{error.code}:{error.message_reference}",
                    ),
                ),
            ),
        )

    @classmethod
    def timeout_output(cls, node_input: NodeInput, message_reference: str) -> NodeOutput:
        return cls.error_output(
            node_input,
            TypedNodeError(code="node_timeout", message_reference=message_reference, retryable=True),
        )

    @staticmethod
    def cancellation_output(node_input: NodeInput) -> NodeOutput:
        return NodeOutput(run_id=node_input.run_id, node_id=node_input.node_id, status="cancelled")

    def conformance(
        self, handlers: Mapping[str, GraphNode], fixtures: Mapping[str, NodeInput]
    ) -> NodeConformanceReport:
        results: list[NodeConformanceResult] = []
        for node_id, handler in handlers.items():
            failures: list[str] = []
            fixture = fixtures.get(node_id)
            if fixture is None:
                results.append(NodeConformanceResult(node_id=node_id, passed=False, failures=("missing fixture",)))
                continue
            try:
                success = self.invoke(handler, fixture.model_copy(update={"cancellation_requested": False}))
                if success.status != "completed":
                    failures.append("success case did not complete")
                typed_error = self.error_output(
                    fixture,
                    TypedNodeError(code="typed_error", message_reference=f"{node_id}:typed-error"),
                )
                if typed_error.status != "failed" or typed_error.error is None:
                    failures.append("typed error case is malformed")
                timeout = self.timeout_output(fixture, f"{node_id}:timeout")
                if timeout.error is None or timeout.error.code != "node_timeout":
                    failures.append("timeout case is malformed")
                cancelled = self.cancellation_output(fixture)
                if cancelled.status != "cancelled" or cancelled.next_node is not None:
                    failures.append("cancellation case is malformed")
            except Exception as exc:  # noqa: BLE001 - report node-specific conformance failures.
                failures.append(str(exc))
            results.append(NodeConformanceResult(node_id=node_id, passed=not failures, failures=tuple(failures)))
        return NodeConformanceReport(results=tuple(results))
