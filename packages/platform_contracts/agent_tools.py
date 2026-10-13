"""Versioned agent tool surface over the governed analytics service (ADS-060).

Every tool maps to one existing `GovernedAnalyzeService` operation (or, for `evidence`, one sealed-envelope read), so a
tool call passes through the same authorization, idempotency, and audit boundaries as a REST call. Arguments are strict
(unknown fields are rejected, sizes are bounded); results carry stable codes and never SQL, physical names, policy
values, or free-text reasons. Changing any schema changes `catalog_digest()`, which a test pins.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.platform_contracts.analytics_v2_api import AnalyzeRunResponse

TOOL_CATALOG_VERSION = "agent-tools-v1"
_HEX64 = r"^[0-9a-f]{64}$"
_RUN_ID = r"^[A-Za-z0-9._:-]{1,128}$"
_KEY = r"^[A-Za-z0-9._:-]{8,128}$"
ToolName = Literal[
    "analytics.analyze", "analytics.status", "analytics.clarify", "analytics.review", "analytics.evidence"
]
Effect = Literal["read", "write", "decision"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalyzeArgs(_Strict):
    purpose: str = Field(min_length=1, max_length=255)
    request_text: str = Field(min_length=3, max_length=2_000)
    idempotency_key: str = Field(pattern=_KEY)


class StatusArgs(_Strict):
    purpose: str = Field(min_length=1, max_length=255)
    run_id: str = Field(pattern=_RUN_ID)


class ClarifyArgs(_Strict):
    purpose: str = Field(min_length=1, max_length=255)
    run_id: str = Field(pattern=_RUN_ID)
    ambiguity_code: Literal["metric", "dataset", "grain", "time", "filter"]
    selected_id: str = Field(min_length=1, max_length=255)


class ReviewArgs(_Strict):
    purpose: str = Field(min_length=1, max_length=255)
    run_id: str = Field(pattern=_RUN_ID)
    decision: Literal["approved", "rejected"]
    plan_fingerprint: str = Field(min_length=64, max_length=128)
    note: str | None = Field(default=None, max_length=2_000)


class EvidenceArgs(_Strict):
    purpose: str = Field(min_length=1, max_length=255)
    run_id: str = Field(pattern=_RUN_ID)


class ToolSpec(_Strict):
    name: ToolName
    title: str
    description: str
    effect: Effect
    requires_idempotency_key: bool
    human_only: bool


ARGUMENT_MODELS: dict[str, type[BaseModel]] = {
    "analytics.analyze": AnalyzeArgs,
    "analytics.status": StatusArgs,
    "analytics.clarify": ClarifyArgs,
    "analytics.review": ReviewArgs,
    "analytics.evidence": EvidenceArgs,
}

TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="analytics.analyze",
        title="Ask a governed analytics question",
        description=(
            "Start or replay a governed run for a natural-language question. The same idempotency key and question "
            "return the same run; reusing a key with a different question is refused. The outcome is an answer, a "
            "clarification question, a review pause, a refusal, or a failure."
        ),
        effect="write",
        requires_idempotency_key=True,
        human_only=False,
    ),
    ToolSpec(
        name="analytics.status",
        title="Read a run's current state and outcome",
        description="Return the state and outcome of one run. Scoped to the caller's tenant and purpose.",
        effect="read",
        requires_idempotency_key=False,
        human_only=False,
    ),
    ToolSpec(
        name="analytics.clarify",
        title="Answer a clarification question",
        description=(
            "Pick one of the offered candidates for a pending ambiguity. Only the original requester may clarify; "
            "a run allows at most two clarification turns."
        ),
        effect="write",
        requires_idempotency_key=False,
        human_only=False,
    ),
    ToolSpec(
        name="analytics.review",
        title="Approve or reject a paused run",
        description=(
            "Decide a pending human review against the plan fingerprint. **Human-only:** automated, service, agent, "
            "and delegated identities are refused; a requester can never approve their own run."
        ),
        effect="decision",
        requires_idempotency_key=False,
        human_only=True,
    ),
    ToolSpec(
        name="analytics.evidence",
        title="Read a run's sealed evidence summary",
        description=(
            "Return the sealed evidence of a terminal run: fingerprints, policy and cost decisions, result validation, "
            "error codes, and the evidence-chain position. Never includes SQL, rows, or policy values."
        ),
        effect="read",
        requires_idempotency_key=False,
        human_only=False,
    ),
)


class ToolCall(_Strict):
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolError(_Strict):
    code: str = Field(min_length=1, max_length=100)
    status: int = Field(ge=400, le=599)


class EvidenceSummary(_Strict):
    """A data-free view of a sealed `EvidenceEnvelope` plus its position in the tenant's chain."""

    envelope_id: str
    content_fingerprint: str = Field(pattern=_HEX64)
    chain_seq: int = Field(ge=1)
    chain_hash: str = Field(pattern=_HEX64)
    run_id: str
    terminal_kind: str
    context_snapshot_id: str
    semantic_contract: str | None = None
    intent_fingerprint: str | None = None
    policy_effect: str | None = None
    policy_version: str | None = None
    policy_reasons: tuple[str, ...] = ()
    estimated_cost_units: float | None = None
    observed_cost_units: float | None = None
    approval_state: str | None = None
    validation_status: str | None = None
    validation_fingerprint: str | None = None
    result_fingerprint: str | None = None
    plan_fingerprint: str | None = None
    row_count: int | None = None
    issue_codes: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()
    clarification_codes: tuple[str, ...] = ()
    transition_count: int = Field(ge=1)
    completed_at: datetime


class ToolResult(_Strict):
    catalog_version: Literal["agent-tools-v1"] = TOOL_CATALOG_VERSION
    tool: str
    ok: bool
    run: AnalyzeRunResponse | None = None
    evidence: EvidenceSummary | None = None
    error: ToolError | None = None


def catalog() -> list[dict[str, Any]]:
    """The machine-readable catalogue: each tool's metadata and its strict JSON schema."""
    return [{**spec.model_dump(), "arguments": ARGUMENT_MODELS[spec.name].model_json_schema()} for spec in TOOLS]


def catalog_digest() -> str:
    body = json.dumps({"version": TOOL_CATALOG_VERSION, "tools": catalog()}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()
