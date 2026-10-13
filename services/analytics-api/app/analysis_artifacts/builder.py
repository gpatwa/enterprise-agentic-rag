"""Build, verify, and present portable analysis artifacts (ADS-062).

Everything here works from the public run response and the sealed-evidence summary, the same two things the REST API and
the agent tool surface already expose, so every surface produces the same artifact for the same run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.agent_tools.dispatcher import summarize_evidence
from app.runtime.analyze_service import GovernedAnalyzeService
from app.runtime.evidence_store import EvidenceNotFoundError, EvidenceStore
from packages.platform_contracts.agent_tools import EvidenceSummary
from packages.platform_contracts.analysis_artifact import (
    AnalysisArtifact,
    ArtifactClaim,
    ArtifactEvidence,
    ArtifactResult,
    ArtifactVisualization,
    rows_digest,
    seal,
)
from packages.platform_contracts.analytics_v2_api import AnalyzeRunResponse
from packages.platform_contracts.security import AnalyticsIdentity


class ArtifactError(Exception):
    """The artifact cannot be built; `code` is stable and carries no content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def build_artifact(
    run: AnalyzeRunResponse,
    evidence: EvidenceSummary,
    *,
    tenant_id: str,
    purpose: str,
    include_rows: bool = False,
) -> AnalysisArtifact:
    if run.state != "terminal" or run.outcome is None:
        raise ArtifactError("run_not_terminal")
    if evidence.run_id != run.run_id:
        raise ArtifactError("evidence_run_mismatch")
    outcome = run.outcome
    values: dict[str, Any] = dict(
        run_id=run.run_id,
        tenant_id=tenant_id,
        purpose=purpose,
        outcome=outcome.outcome,
        semantic_contract=evidence.semantic_contract,
        context_snapshot_id=evidence.context_snapshot_id,
        evidence=ArtifactEvidence(
            envelope_id=evidence.envelope_id,
            content_fingerprint=evidence.content_fingerprint,
            chain_seq=evidence.chain_seq,
            chain_hash=evidence.chain_hash,
            terminal_kind=evidence.terminal_kind,
            result_fingerprint=evidence.result_fingerprint,
            validation_status=evidence.validation_status,
        ),
    )
    if outcome.outcome == "answer":
        if outcome.evidence.result_fingerprint != evidence.result_fingerprint:
            raise ArtifactError("evidence_result_mismatch")
        rows = tuple(tuple(row) for row in outcome.result.rows)
        values.update(
            answer=outcome.answer,
            explanation_status=outcome.explanation_status,
            claims=tuple(ArtifactClaim(text=c.text, cites=tuple(c.cites)) for c in outcome.claims),
            visualization=ArtifactVisualization(
                kind=outcome.visualization.kind,
                x_column=outcome.visualization.x_column,
                y_columns=tuple(outcome.visualization.y_columns),
                semantic_ids=tuple(outcome.visualization.semantic_ids),
                row_limit=outcome.visualization.row_limit,
            ),
            result=ArtifactResult(
                columns=tuple(outcome.result.columns),
                row_count=outcome.result.row_count,
                rows_sha256=rows_digest(rows),
                rows=rows if include_rows else None,
            ),
            metric_ids=tuple(outcome.evidence.metric_ids),
            dimension_ids=tuple(outcome.evidence.dimension_ids),
            rows_included=include_rows,
        )
    elif outcome.outcome in {"refuse", "failed"}:
        values["reason_code"] = outcome.reason_code if outcome.outcome == "refuse" else outcome.error_code
    else:
        raise ArtifactError("run_not_terminal")  # clarify and review outcomes are not finished analyses
    try:
        return seal(**values)
    except ValidationError as exc:
        raise ArtifactError("artifact_inconsistent") from exc


def artifact_for_run(
    service: GovernedAnalyzeService,
    evidence_store: EvidenceStore,
    identity: AnalyticsIdentity,
    *,
    purpose: str,
    run_id: str,
    include_rows: bool = False,
) -> AnalysisArtifact:
    """Authorize through the service (tenant and purpose scope), read the sealed evidence, and build the artifact."""
    run = service.status(identity, purpose=purpose, run_id=run_id)
    if run.state != "terminal":
        raise ArtifactError("run_not_terminal")
    try:
        envelope = evidence_store.get(run_id, tenant_id=identity.tenant_id, purpose=purpose)
        seq, chain_hash = evidence_store.seal_position(run_id, tenant_id=identity.tenant_id, purpose=purpose)
    except EvidenceNotFoundError as exc:
        raise ArtifactError("evidence_unavailable") from exc
    return build_artifact(
        run,
        summarize_evidence(envelope, seq, chain_hash),
        tenant_id=identity.tenant_id,
        purpose=purpose,
        include_rows=include_rows,
    )


def parse_artifact(payload: str | bytes) -> AnalysisArtifact:
    """Strictly parse a stored artifact; its fingerprint and rows hash are re-checked by the model."""
    try:
        return AnalysisArtifact.model_validate_json(payload)
    except ValidationError as exc:
        raise ArtifactError("artifact_invalid") from exc


@dataclass(frozen=True)
class ArtifactVerification:
    ok: bool
    problems: tuple[str, ...]


def verify_artifact(
    artifact: AnalysisArtifact, evidence_store: EvidenceStore | None = None, *, purpose: str | None = None
) -> ArtifactVerification:
    """Check the artifact against the live sealed evidence and the tenant's chain (the model already checked itself)."""
    problems: list[str] = []
    if evidence_store is None:
        return ArtifactVerification(True, ())
    try:
        envelope = evidence_store.get(
            artifact.run_id, tenant_id=artifact.tenant_id, purpose=purpose or artifact.purpose
        )
        seq, chain_hash = evidence_store.seal_position(
            artifact.run_id, tenant_id=artifact.tenant_id, purpose=purpose or artifact.purpose
        )
    except EvidenceNotFoundError:
        return ArtifactVerification(False, ("evidence_missing",))
    ref = artifact.evidence
    if (ref.envelope_id, ref.content_fingerprint) != (envelope.envelope_id, envelope.content_fingerprint):
        problems.append("evidence_envelope_mismatch")
    if (ref.chain_seq, ref.chain_hash) != (seq, chain_hash):
        problems.append("evidence_chain_position_mismatch")
    if envelope.context_snapshot_id != artifact.context_snapshot_id:
        problems.append("context_snapshot_mismatch")
    if envelope.semantic_contract != artifact.semantic_contract:
        problems.append("semantic_contract_mismatch")
    result_fp = envelope.result.result_fingerprint if envelope.result else None
    if result_fp != ref.result_fingerprint:
        problems.append("result_fingerprint_mismatch")
    try:
        evidence_store.verify_chain(artifact.tenant_id)
    except Exception:  # noqa: BLE001 - any chain failure invalidates the pointer; details stay out of the result.
        problems.append("evidence_chain_broken")
    return ArtifactVerification(not problems, tuple(problems))


def canonical_view(artifact: AnalysisArtifact) -> dict[str, Any]:
    """What every surface (web, REST, agent) shows for an artifact, derived from the artifact alone."""
    result = artifact.result
    return {
        "artifact_id": artifact.artifact_id,
        "run_id": artifact.run_id,
        "outcome": artifact.outcome,
        "headline": artifact.answer or artifact.reason_code,
        "explanation_status": artifact.explanation_status,
        "claims": [{"text": c.text, "cites": list(c.cites)} for c in artifact.claims],
        "table": (
            {
                "columns": list(result.columns),
                "row_count": result.row_count,
                "rows": [list(r) for r in result.rows] if result.rows is not None else None,
            }
            if result
            else None
        ),
        "chart": (
            {
                "kind": artifact.visualization.kind,
                "x": artifact.visualization.x_column,
                "y": list(artifact.visualization.y_columns),
                "semantic_ids": list(artifact.visualization.semantic_ids),
            }
            if artifact.visualization
            else None
        ),
        "provenance": {
            "semantic_contract": artifact.semantic_contract,
            "metrics": list(artifact.metric_ids),
            "dimensions": list(artifact.dimension_ids),
            "context_snapshot": artifact.context_snapshot_id,
            "evidence": artifact.evidence.envelope_id,
            "chain_seq": artifact.evidence.chain_seq,
        },
    }


def render_text(artifact: AnalysisArtifact) -> str:
    """A plain-text rendering that depends only on the canonical view."""
    view = canonical_view(artifact)
    lines = [f"[{view['outcome']}] {view['headline']}"]
    lines += [f"- {c['text']} ({', '.join(c['cites'])})" for c in view["claims"]]
    if view["table"]:
        lines.append(f"table: {', '.join(view['table']['columns'])} ({view['table']['row_count']} rows)")
        for row in view["table"]["rows"] or []:
            lines.append("  " + " | ".join("" if cell is None else str(cell) for cell in row))
    if view["chart"]:
        lines.append(f"chart: {view['chart']['kind']} x={view['chart']['x']} y={view['chart']['y']}")
    lines.append(f"evidence: {view['provenance']['evidence']} @ chain {view['provenance']['chain_seq']}")
    return "\n".join(lines)
