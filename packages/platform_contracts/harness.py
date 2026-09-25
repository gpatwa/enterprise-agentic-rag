"""Versioned scenario and expected-trace contracts for the agent harness."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.platform_contracts.agent_runtime import RunStatus, TerminalKind, is_legal_transition

HARNESS_SCHEMA_VERSION = "v1"


class ExpectedTraceStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    from_node: str = Field(min_length=1, max_length=255)
    to_node: str | None = Field(default=None, max_length=255)
    to_status: RunStatus

    @model_validator(mode="after")
    def validate_transition(self) -> "ExpectedTraceStep":
        return self


class ExpectedTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    graph_version: str = Field(min_length=1, max_length=255)
    steps: tuple[ExpectedTraceStep, ...] = Field(min_length=1, max_length=1_000)
    terminal_kind: TerminalKind

    @model_validator(mode="after")
    def validate_sequence(self) -> "ExpectedTrace":
        for step in self.steps:
            if not is_legal_transition(step.from_node, step.to_node, step.to_status, self.graph_version):
                raise ValueError(
                    f"illegal expected transition from {step.from_node} to {step.to_node or step.to_status}"
                )
        sequences = [step.sequence for step in self.steps]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("expected trace sequences must be contiguous and start at one")
        for previous, current in zip(self.steps, self.steps[1:]):
            if previous.to_node != current.from_node:
                raise ValueError("expected trace steps must connect in order")
        if self.steps[-1].to_status != "terminal":
            raise ValueError("expected trace must terminate with a terminal step")
        return self


class HarnessScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_version: Literal["v1"] = HARNESS_SCHEMA_VERSION
    scenario_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    request: str = Field(min_length=3, max_length=2_000)
    context_snapshot_id: str = Field(min_length=1, max_length=255)
    graph_version: str = Field(min_length=1, max_length=255)
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_trace: ExpectedTrace
    fixture_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_graph_version(self) -> "HarnessScenario":
        if self.expected_trace.graph_version != self.graph_version:
            raise ValueError("scenario graph_version does not match expected trace")
        expected = _digest(self._digest_values())
        if expected != self.fixture_digest:
            raise ValueError("fixture_digest does not match scenario content")
        return self

    def _digest_values(self) -> dict[str, Any]:
        values = self.model_dump(mode="json")
        values.pop("fixture_digest", None)
        return values

    @classmethod
    def build(
        cls,
        *,
        scenario_id: str,
        tenant_id: str,
        purpose: str,
        request: str,
        context_snapshot_id: str,
        graph_version: str,
        expected_trace: ExpectedTrace,
        inputs: dict[str, Any] | None = None,
    ) -> "HarnessScenario":
        values: dict[str, Any] = {
            "scenario_version": HARNESS_SCHEMA_VERSION,
            "scenario_id": scenario_id,
            "tenant_id": tenant_id,
            "purpose": purpose,
            "request": request,
            "context_snapshot_id": context_snapshot_id,
            "graph_version": graph_version,
            "inputs": inputs or {},
            "expected_trace": expected_trace,
        }
        digest_values = {**values, "expected_trace": expected_trace.model_dump(mode="json")}
        return cls(**values, fixture_digest=_digest(digest_values))


class HarnessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: Literal["v1"] = HARNESS_SCHEMA_VERSION
    scenario_id: str
    scenario_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    semantic_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    run_id: str
    logical_time: str
    random_sample: int
    tokens_used: int = Field(ge=0)
    cost_units: float = Field(ge=0)


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
