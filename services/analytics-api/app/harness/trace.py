"""Redacted trace capture and deterministic replay for local harness runs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.platform_contracts.agent_runtime import Transition

if TYPE_CHECKING:
    from app.harness.graph import GraphExecutionResult, GraphHarness
    from packages.platform_contracts.determinism import DeterministicControls
    from packages.platform_contracts.harness import HarnessScenario

TRACE_SCHEMA_VERSION = "v1"
REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "authorization", "cookie", "password", "secret", "token", "api_key", "apikey",
    "credential", "private_key", "access_key", "raw_prompt", "raw_content",
)


class TraceReplayError(RuntimeError):
    """Raised when a stored trace cannot be reproduced by the local harness."""


class CapturedTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_version: Literal["v1"] = TRACE_SCHEMA_VERSION
    trace_id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    scenario_id: str = Field(min_length=1, max_length=255)
    scenario_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1, max_length=255)
    graph_version: str = Field(min_length=1, max_length=255)
    terminal_kind: str = Field(min_length=1, max_length=64)
    transitions: tuple[Transition, ...] = Field(min_length=1, max_length=1_000)
    redacted_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_digest(self) -> "CapturedTrace":
        expected = _digest(self._digest_values())
        if expected != self.trace_id:
            raise ValueError("trace_id does not match captured trace content")
        return self

    def _digest_values(self) -> dict[str, Any]:
        values = self.model_dump(mode="json")
        values.pop("trace_id", None)
        return values

    @classmethod
    def capture(cls, scenario: "HarnessScenario", result: "GraphExecutionResult") -> "CapturedTrace":
        payload = redact_payload(result.final_payload)
        values = {
            "trace_version": TRACE_SCHEMA_VERSION,
            "scenario_id": scenario.scenario_id,
            "scenario_digest": scenario.fixture_digest,
            "run_id": result.run_id,
            "graph_version": result.graph_version,
            "terminal_kind": result.state.terminal_outcome.kind if result.state.terminal_outcome else "unknown",
            "transitions": result.transitions,
            "redacted_payload": payload,
        }
        digest_values = {
            **values,
            "transitions": [transition.model_dump(mode="json") for transition in result.transitions],
        }
        return cls(**values, trace_id=_digest(digest_values))

    def export_json(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2) + "\n")

    @classmethod
    def load_json(cls, path: str | Path) -> "CapturedTrace":
        return cls.model_validate_json(Path(path).read_text())

    def replay(
        self, scenario: "HarnessScenario", harness: "GraphHarness", controls: "DeterministicControls"
    ) -> "GraphExecutionResult":
        if scenario.scenario_id != self.scenario_id or scenario.fixture_digest != self.scenario_digest:
            raise TraceReplayError("scenario identity or fixture digest does not match stored trace")
        result = harness.run(scenario, controls)
        if _transition_signatures(result.transitions) != _transition_signatures(self.transitions):
            raise TraceReplayError("replayed transition trace differs from stored trace")
        observed_kind = result.state.terminal_outcome.kind if result.state.terminal_outcome else "unknown"
        if observed_kind != self.terminal_kind:
            raise TraceReplayError(
                f"replayed terminal outcome differs: expected {self.terminal_kind}, observed {observed_kind}"
            )
        return result


def redact_payload(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact secret-like fields and bound stored string payloads."""
    if key and any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return REDACTED
    if isinstance(value, dict):
        return {str(item_key): redact_payload(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
    if isinstance(value, str) and len(value) > 512:
        return f"{value[:512]}... [TRUNCATED]"
    return value


def _transition_signatures(transitions: tuple[Transition, ...] | list[Transition]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (item.sequence, item.from_node, item.to_node, item.from_status, item.to_status, item.attempt)
        for item in transitions
    )


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
