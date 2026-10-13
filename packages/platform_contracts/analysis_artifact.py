"""Portable, machine-readable analysis artifact (ADS-062).

One finished governed run, captured so that web, REST, and agent surfaces can each present and replay it identically.
It is content-addressed: `artifact_id` derives from everything the run decided (answer, claims and their citations,
result shape and a hash of the rows, visualization spec, semantic IDs, snapshot, and the sealed-evidence pointer) and
from nothing volatile (no timestamps, no user IDs, no SQL, no policy values). Rows are excluded by default; when a
caller opts in they are bound by hash, and including them never changes the artifact's ID.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ARTIFACT_VERSION = "analysis-artifact-v1"
_HEX64 = r"^[0-9a-f]{64}$"
Cell = str | int | float | bool | None
_OUTCOME_KINDS: dict[str, set[str]] = {
    "answer": {"succeeded"},
    "refuse": {"refused", "review_required"},
    "failed": {"failed", "cancelled"},
}


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactClaim(_Frozen):
    text: str = Field(min_length=1, max_length=400)
    cites: tuple[str, ...] = Field(min_length=1, max_length=20)


class ArtifactVisualization(_Frozen):
    kind: Literal["stat", "line", "bar", "table"]
    x_column: int | None = Field(default=None, ge=0)
    y_columns: tuple[int, ...] = ()
    semantic_ids: tuple[str, ...] = ()
    row_limit: int = Field(ge=1)


class ArtifactResult(_Frozen):
    columns: tuple[str, ...] = Field(max_length=50)
    row_count: int = Field(ge=0)
    rows_sha256: str = Field(pattern=_HEX64)
    rows: tuple[tuple[Cell, ...], ...] | None = None


class ArtifactEvidence(_Frozen):
    envelope_id: str = Field(min_length=1, max_length=255)
    content_fingerprint: str = Field(pattern=_HEX64)
    chain_seq: int = Field(ge=1)
    chain_hash: str = Field(pattern=_HEX64)
    terminal_kind: str = Field(min_length=1, max_length=64)
    result_fingerprint: str | None = Field(default=None, pattern=_HEX64)
    validation_status: str | None = None


def rows_digest(rows: Any) -> str:
    body = json.dumps([list(row) for row in rows], separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


class AnalysisArtifact(_Frozen):
    artifact_version: Literal["analysis-artifact-v1"] = ARTIFACT_VERSION
    run_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    outcome: Literal["answer", "refuse", "failed"]
    reason_code: str | None = Field(default=None, max_length=100)
    answer: str | None = None
    explanation_status: Literal["grounded", "evidence_only"] | None = None
    claims: tuple[ArtifactClaim, ...] = ()
    visualization: ArtifactVisualization | None = None
    result: ArtifactResult | None = None
    semantic_contract: str | None = Field(default=None, max_length=512)
    metric_ids: tuple[str, ...] = ()
    dimension_ids: tuple[str, ...] = ()
    context_snapshot_id: str = Field(min_length=1, max_length=255)
    evidence: ArtifactEvidence
    rows_included: bool = False
    content_fingerprint: str = Field(pattern=_HEX64)

    @property
    def artifact_id(self) -> str:
        return f"artifact:{self.content_fingerprint[:32]}"

    def core(self) -> dict[str, Any]:
        """What the ID covers: everything except the rows themselves and whether they were included."""
        payload = self.model_dump(mode="json", exclude={"content_fingerprint", "rows_included"})
        if payload.get("result"):
            payload["result"].pop("rows", None)
        return payload

    @model_validator(mode="after")
    def consistent(self) -> "AnalysisArtifact":
        if self.evidence.terminal_kind not in _OUTCOME_KINDS[self.outcome]:
            raise ValueError("artifact outcome does not match its sealed evidence")
        if self.outcome == "answer":
            if not (self.answer and self.result and self.visualization and self.evidence.result_fingerprint):
                raise ValueError("an answer artifact carries its answer, result, visualization, and result fingerprint")
        elif self.answer or self.result or self.claims or self.visualization or not self.reason_code:
            raise ValueError("a refusal or failure artifact carries a reason code and no answer material")
        if self.result:
            rows = self.result.rows
            if self.rows_included != (rows is not None):
                raise ValueError("rows_included must match whether rows are present")
            if rows is not None and (
                len(rows) != self.result.row_count or rows_digest(rows) != self.result.rows_sha256
            ):
                raise ValueError("artifact rows do not match their hash")
        elif self.rows_included:
            raise ValueError("an artifact without a result cannot include rows")
        if fingerprint_of(self.core()) != self.content_fingerprint:
            raise ValueError("artifact content_fingerprint does not match content")
        return self


def fingerprint_of(core: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seal(**values: Any) -> AnalysisArtifact:
    """Build an artifact, computing its content fingerprint from the validated core."""
    probe = AnalysisArtifact.model_construct(**values, content_fingerprint="0" * 64)
    core = probe.model_dump(mode="json", exclude={"content_fingerprint", "rows_included"})
    if core.get("result"):
        core["result"].pop("rows", None)
    return AnalysisArtifact(**values, content_fingerprint=fingerprint_of(core))
