"""ADS-062: a portable, content-addressed analysis artifact that replays identically across web, REST, and agent surfaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from reference_stack.stack import build_stack
from sqlalchemy import text

from app.agent_tools import AgentToolSurface
from app.analysis_artifacts import (
    ArtifactError,
    artifact_for_run,
    build_artifact,
    canonical_view,
    parse_artifact,
    render_text,
    verify_artifact,
)
from packages.platform_contracts.agent_tools import EvidenceSummary
from packages.platform_contracts.analysis_artifact import AnalysisArtifact, rows_digest
from packages.platform_contracts.analytics_v2_api import AnalyzeRunResponse

SERVICE = Path(__file__).resolve().parent.parent
PURPOSE, TENANT, QUESTION = "analytics", "tenant-a", "Show monthly revenue"
URL = "/api/v2/analytics"


def _stack(tmp_path, name="a", **kwargs):
    stack = build_stack("duckdb", tmp_path / name, **kwargs)
    return stack, stack.service(), stack.verifier().verify(stack.token("requester"))


def _rest_run(stack, key="rest-key-0001", question=QUESTION) -> AnalyzeRunResponse:
    client = TestClient(stack.app())
    response = client.post(
        f"{URL}/analyze",
        json={"request_text": question, "purpose": PURPOSE},
        headers={"Authorization": f"Bearer {stack.token('requester')}", "Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    return AnalyzeRunResponse.model_validate(response.json())


def _evidence(stack, who, run_id) -> EvidenceSummary:
    surface = AgentToolSurface(stack.service(), stack.evidence)
    result = surface.call(who, {"tool": "analytics.evidence", "arguments": {"purpose": PURPOSE, "run_id": run_id}})
    assert result.ok, result.error
    return result.evidence


# ---- the artifact holds what the run decided, and nothing volatile or sensitive ----


def test_an_answer_artifact_captures_the_decided_content_without_rows_by_default(tmp_path):
    stack, service, who = _stack(tmp_path)
    artifact = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=_rest_run(stack).run_id)
    assert artifact.outcome == "answer" and artifact.artifact_id.startswith("artifact:")
    assert artifact.claims and all(c.cites for c in artifact.claims) and artifact.visualization.kind
    assert artifact.result.row_count > 0 and artifact.result.rows is None and not artifact.rows_included
    assert artifact.result.rows_sha256 and artifact.semantic_contract == "sales-core@v1"
    assert artifact.metric_ids and artifact.evidence.terminal_kind == "succeeded"
    dumped = artifact.model_dump_json().lower()
    for forbidden in ("select ", "sales_orders", "policy_values", "generated_at", "user_id", "requester", "query_id"):
        assert forbidden not in dumped, forbidden
    assert artifact.evidence.result_fingerprint == _evidence(stack, who, artifact.run_id).result_fingerprint


def test_rows_are_opt_in_bound_by_hash_and_never_change_the_artifact_id(tmp_path):
    stack, service, who = _stack(tmp_path)
    run_id = _rest_run(stack).run_id
    plain = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=run_id)
    full = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=run_id, include_rows=True)
    assert full.rows_included and full.result.rows and len(full.result.rows) == full.result.row_count
    assert full.artifact_id == plain.artifact_id and full.result.rows_sha256 == plain.result.rows_sha256
    assert rows_digest(full.result.rows) == full.result.rows_sha256
    assert render_text(full) != render_text(plain) and canonical_view(plain)["table"]["rows"] is None


# ---- stable IDs and replay across surfaces ----


def test_every_surface_produces_the_same_artifact_and_view_for_the_same_run(tmp_path):
    stack, service, who = _stack(tmp_path)
    rest = _rest_run(stack)
    surface = AgentToolSurface(service, stack.evidence)
    via_tool = surface.call(
        who,
        {
            "tool": "analytics.analyze",
            "arguments": {"purpose": PURPOSE, "request_text": QUESTION, "idempotency_key": "rest-key-0001"},
        },
    )
    evidence = _evidence(stack, who, rest.run_id)
    from_rest = build_artifact(rest, evidence, tenant_id=TENANT, purpose=PURPOSE)
    from_tool = build_artifact(via_tool.run, evidence, tenant_id=TENANT, purpose=PURPOSE)
    from_service = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=rest.run_id)
    assert from_rest == from_tool == from_service and from_rest.artifact_id == from_tool.artifact_id
    assert canonical_view(from_rest) == canonical_view(from_tool) == canonical_view(from_service)
    assert render_text(from_rest) == render_text(from_tool)


def test_a_stored_artifact_replays_without_the_service_and_the_id_is_stable(tmp_path):
    stack, service, who = _stack(tmp_path)
    run_id = _rest_run(stack).run_id
    artifact = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=run_id, include_rows=True)
    stored = artifact.model_dump_json()
    replayed = parse_artifact(stored)
    assert replayed == artifact and replayed.artifact_id == artifact.artifact_id
    assert canonical_view(replayed) == canonical_view(artifact) and render_text(replayed) == render_text(artifact)
    again = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=run_id, include_rows=True)
    assert again.artifact_id == artifact.artifact_id  # the response's generated_at never enters the ID
    other = _rest_run(stack, key="rest-key-0002")
    assert (
        artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=other.run_id).artifact_id
        != artifact.artifact_id
    )
    assert json.loads(stored)["artifact_version"] == "analysis-artifact-v1"


# ---- tamper detection ----


def _tamper(artifact, mutate):
    payload = json.loads(artifact.model_dump_json())
    mutate(payload)
    return json.dumps(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(answer="Revenue was ten times higher."),
        lambda p: p["claims"][0].update(text="Revenue doubled."),
        lambda p: p["claims"][0].update(cites=["metric:profit"]),
        lambda p: p["result"].update(row_count=p["result"]["row_count"] + 1),
        lambda p: p["result"].update(rows_sha256="0" * 64),
        lambda p: p["evidence"].update(chain_seq=p["evidence"]["chain_seq"] + 1),
        lambda p: p["evidence"].update(terminal_kind="refused"),
        lambda p: p.update(semantic_contract="sales-core@v9"),
        lambda p: p.update(context_snapshot_id="other-snapshot"),
        lambda p: p.update(tenant_id="tenant-b"),
        lambda p: p.update(content_fingerprint="0" * 64),
        lambda p: p.update(sql="DROP TABLE orders"),
        lambda p: p["visualization"].update(kind="bar" if p["visualization"]["kind"] != "bar" else "line"),
    ],
)
def test_any_change_to_a_stored_artifact_is_rejected(tmp_path, mutate):
    stack, service, who = _stack(tmp_path)
    artifact = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=_rest_run(stack).run_id)
    with pytest.raises(ArtifactError, match="artifact_invalid"):
        parse_artifact(_tamper(artifact, mutate))


def test_changed_rows_are_caught_by_their_hash_even_when_the_fingerprint_is_untouched(tmp_path):
    stack, service, who = _stack(tmp_path)
    artifact = artifact_for_run(
        service, stack.evidence, who, purpose=PURPOSE, run_id=_rest_run(stack).run_id, include_rows=True
    )
    forged = _tamper(artifact, lambda p: p["result"]["rows"][0].__setitem__(1, 999999))
    with pytest.raises(ArtifactError):
        parse_artifact(forged)
    with pytest.raises(ValidationError, match="rows"):
        AnalysisArtifact.model_validate({**artifact.model_dump(), "rows_included": False})


# ---- verification against the sealed evidence ----


def test_an_artifact_verifies_against_the_live_evidence_and_chain(tmp_path):
    stack, service, who = _stack(tmp_path)
    artifact = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=_rest_run(stack).run_id)
    assert verify_artifact(artifact).ok  # self-consistency only, no store
    assert verify_artifact(artifact, stack.evidence).ok
    second = _rest_run(stack, key="rest-key-0002")
    assert verify_artifact(artifact, stack.evidence).ok  # a later run extends the chain without moving this position
    assert artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=second.run_id).evidence.chain_seq == 2


def test_verification_reports_missing_and_rewritten_evidence(tmp_path):
    stack, service, who = _stack(tmp_path)
    artifact = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=_rest_run(stack).run_id)
    other_stack, _, _ = _stack(tmp_path, "empty")
    assert verify_artifact(artifact, other_stack.evidence).problems == ("evidence_missing",)
    with stack.evidence.engine.begin() as connection:  # an operator with schema rights bypasses the trigger
        connection.execute(text("DROP TRIGGER trg_evidence_envelopes_no_update"))
        connection.execute(text("UPDATE analytics_evidence_envelopes SET chain_hash=:h"), {"h": "f" * 64})
    result = verify_artifact(artifact, stack.evidence)
    assert (
        not result.ok
        and "evidence_chain_position_mismatch" in result.problems
        and "evidence_chain_broken" in result.problems
    )


# ---- other outcomes, and what cannot become an artifact ----


def test_refused_runs_have_a_reason_code_artifact_with_no_answer_material(tmp_path):
    stack, service, who = _stack(tmp_path, denied=True)
    run = _rest_run(stack)
    artifact = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=run.run_id)
    assert artifact.outcome == "refuse" and artifact.reason_code == "policy_restricted"
    assert (
        artifact.answer is None and artifact.result is None and artifact.claims == () and artifact.visualization is None
    )
    assert canonical_view(artifact)["headline"] == "policy_restricted" and verify_artifact(artifact, stack.evidence).ok


def test_unfinished_foreign_or_inconsistent_runs_cannot_become_artifacts(tmp_path):
    stack, service, who = _stack(tmp_path, review_threshold=1e-9)
    paused = stack.service().analyze(who, purpose=PURPOSE, idempotency_key="paused-key-0001", request_text=QUESTION)
    assert paused.state == "waiting_review"
    with pytest.raises(ArtifactError, match="run_not_terminal"):
        artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=paused.run_id)
    done_stack, done_service, done_who = _stack(tmp_path, "done")
    run = _rest_run(done_stack)
    outsider = done_stack.verifier().verify(done_stack.token("outsider", tenant="tenant-b"))
    from app.runtime.analyze_service import ServiceError

    with pytest.raises(ServiceError) as caught:
        artifact_for_run(done_service, done_stack.evidence, outsider, purpose=PURPOSE, run_id=run.run_id)
    assert caught.value.code == "run_not_found"
    evidence = _evidence(done_stack, done_who, run.run_id)
    with pytest.raises(ArtifactError, match="evidence_run_mismatch"):
        build_artifact(run, evidence.model_copy(update={"run_id": "someone-else"}), tenant_id=TENANT, purpose=PURPOSE)
    with pytest.raises(ArtifactError, match="evidence_result_mismatch"):
        build_artifact(
            run, evidence.model_copy(update={"result_fingerprint": "1" * 64}), tenant_id=TENANT, purpose=PURPOSE
        )
    assert run.outcome.outcome == "answer"
    with pytest.raises(ArtifactError, match="run_not_terminal"):
        build_artifact(paused, evidence, tenant_id=TENANT, purpose=PURPOSE)


def test_the_artifact_model_enforces_outcome_and_evidence_consistency(tmp_path):
    stack, service, who = _stack(tmp_path)
    artifact = artifact_for_run(service, stack.evidence, who, purpose=PURPOSE, run_id=_rest_run(stack).run_id)
    base = artifact.model_dump()
    for change in (
        {"evidence": {**base["evidence"], "terminal_kind": "refused"}},
        {"outcome": "refuse", "reason_code": "x"},
        {"answer": None},
        {"rows_included": True},
    ):
        with pytest.raises(ValidationError):
            AnalysisArtifact.model_validate({**base, **change})


def test_nothing_mounts_the_artifact_module_yet():
    for path in (SERVICE / "app/main.py", SERVICE / "app/api_v2.py"):
        assert "app.analysis_artifacts" not in path.read_text(), path.name
