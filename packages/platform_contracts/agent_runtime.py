"""Versioned contracts for bounded agent graph execution.

These contracts describe state and facts exchanged by a runner. They do not
execute nodes, persist checkpoints, or authorize tools.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AGENT_RUNTIME_SCHEMA_VERSION = "v1"

RunStatus = Literal["active", "waiting_approval", "cancel_requested", "terminal"]
NodeStatus = Literal["completed", "failed", "waiting", "cancelled"]
TerminalKind = Literal["succeeded", "refused", "review_required", "clarification_required", "failed", "cancelled"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class EvidenceReference(_Contract):
    evidence_id: str = Field(min_length=1, max_length=255)
    kind: Literal["context", "decision", "tool_result", "transition", "error", "approval"]
    fingerprint: str = Field(min_length=1, max_length=128)
    redacted: bool = True


class RunBudget(_Contract):
    max_transitions: int = Field(default=32, ge=1, le=1_000)
    max_node_attempts: int = Field(default=3, ge=1, le=100)
    deadline: datetime
    max_cost_units: float = Field(default=100, gt=0)

    @model_validator(mode="after")
    def require_timezone(self) -> "RunBudget":
        if self.deadline.tzinfo is None:
            raise ValueError("deadline must include a timezone")
        return self


class CancellationRequest(_Contract):
    requested_by: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1_000)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    policy_source: str = Field(min_length=1, max_length=255)


class RunError(_Contract):
    code: str = Field(min_length=1, max_length=100)
    message_reference: str = Field(min_length=1, max_length=255)
    retryable: bool = False
    evidence: tuple[EvidenceReference, ...] = ()


class TerminalOutcome(_Contract):
    kind: TerminalKind
    summary_reference: str = Field(min_length=1, max_length=255)
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def require_utc_timestamp(self) -> "TerminalOutcome":
        if self.completed_at.tzinfo is None:
            raise ValueError("completed_at must include a timezone")
        return self


class AgentRunState(_Contract):
    """The complete, serializable state boundary for one bounded run."""

    schema_version: Literal["v1"] = AGENT_RUNTIME_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    request_text: str | None = Field(default=None, min_length=3, max_length=2_000)
    graph_version: str = Field(min_length=1, max_length=255)
    current_node: str = Field(min_length=1, max_length=255)
    status: RunStatus = "active"
    transition_count: int = Field(default=0, ge=0)
    context_snapshot_id: str = Field(min_length=1, max_length=255)
    intent: dict[str, Any] | None = None
    policy_decision: dict[str, Any] | None = None
    cost_decision: dict[str, Any] | None = None
    approval_state: dict[str, Any] | None = None
    compiled_plan_reference: str | None = Field(default=None, max_length=255)
    execution_reference: str | None = Field(default=None, max_length=255)
    evidence: tuple[EvidenceReference, ...] = ()
    errors: tuple[RunError, ...] = ()
    budget: RunBudget
    cancellation: CancellationRequest | None = None
    terminal_outcome: TerminalOutcome | None = None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> "AgentRunState":
        if self.transition_count > self.budget.max_transitions:
            raise ValueError("transition_count exceeds max_transitions")
        if self.status == "terminal" and self.terminal_outcome is None:
            raise ValueError("terminal state requires terminal_outcome")
        if self.status != "terminal" and self.terminal_outcome is not None:
            raise ValueError("terminal_outcome is only valid for terminal state")
        if self.status == "cancel_requested" and self.cancellation is None:
            raise ValueError("cancel_requested state requires cancellation")
        return self


class NodeInput(_Contract):
    schema_version: Literal["v1"] = AGENT_RUNTIME_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    request_id: str | None = Field(default=None, min_length=1, max_length=255)
    request_text: str | None = Field(default=None, min_length=3, max_length=2_000)
    node_id: str = Field(min_length=1, max_length=255)
    state_version: int = Field(ge=0)
    context_snapshot_id: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    remaining_budget: RunBudget
    cancellation_requested: bool = False


class NodeOutput(_Contract):
    schema_version: Literal["v1"] = AGENT_RUNTIME_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=255)
    node_id: str = Field(min_length=1, max_length=255)
    status: NodeStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: tuple[EvidenceReference, ...] = ()
    error: RunError | None = None
    next_node: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_result_shape(self) -> "NodeOutput":
        if self.status == "failed" and self.error is None:
            raise ValueError("failed node output requires error")
        if self.status != "failed" and self.error is not None:
            raise ValueError("error is only valid for failed node output")
        if self.status in {"waiting", "completed"} and not self.next_node:
            raise ValueError(f"{self.status} node output requires next_node")
        if self.status in {"cancelled", "failed"} and self.next_node is not None:
            raise ValueError(f"{self.status} node output cannot select next_node")
        return self


class Transition(_Contract):
    schema_version: Literal["v1"] = AGENT_RUNTIME_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    graph_version: str = Field(min_length=1, max_length=255)
    sequence: int = Field(ge=1)
    from_node: str = Field(min_length=1, max_length=255)
    to_node: str | None = Field(default=None, max_length=255)
    from_status: RunStatus
    to_status: RunStatus
    attempt: int = Field(default=1, ge=1)
    idempotency_key: str = Field(min_length=1, max_length=512)
    evidence: tuple[EvidenceReference, ...] = ()

    @model_validator(mode="after")
    def validate_transition_shape(self) -> "Transition":
        if self.to_status == "terminal" and self.to_node is not None:
            raise ValueError("terminal transition cannot target a node")
        if self.to_status != "terminal" and self.to_node is None:
            raise ValueError("non-terminal transition requires to_node")
        if self.from_status == "terminal":
            raise ValueError("terminal state cannot transition")
        if not is_legal_transition(self.from_node, self.to_node, self.to_status):
            raise ValueError(f"illegal transition from {self.from_node} to {self.to_node or self.to_status}")
        return self


LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "create": ("bootstrap",),
    "bootstrap": ("retrieve",),
    "retrieve": ("resolve",),
    "resolve": ("plan",),
    "plan": ("validate",),
    "validate": ("compile",),
    "compile": ("policy",),
    "policy": ("estimate", "approve", "terminal"),
    "estimate": ("approve", "execute", "terminal"),
    "approve": ("execute", "terminal"),
    "execute": ("result_validate",),
    "result_validate": ("explain", "terminal"),
    "explain": ("terminal",),
}


def is_legal_transition(from_node: str, to_node: str | None, to_status: RunStatus) -> bool:
    """Return whether the authored bounded graph permits the transition."""
    if to_status == "terminal":
        # Typed failure and cancellation may terminate at any registered node;
        # ordinary successful progress still follows the authored edge list.
        return from_node in LEGAL_TRANSITIONS
    return to_node in LEGAL_TRANSITIONS.get(from_node, ())
