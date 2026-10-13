"""ADS-060: a strict, scoped, documented, contract-tested agent tool surface over the governed service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from reference_stack.stack import build_stack

from app.agent_tools import AgentToolSurface, caller_kind
from app.agent_tools import catalogue as catalogue_module
from app.runtime.evidence_store import EvidenceNotFoundError
from packages.platform_contracts import agent_tools as contract
from packages.platform_contracts.security import AnalyticsIdentity

SERVICE = Path(__file__).resolve().parent.parent
PURPOSE = "analytics"
QUESTION = "Show monthly revenue"


def _surface(tmp_path, name="a", *, with_evidence=True, **kwargs):
    stack = build_stack("duckdb", tmp_path / name, **kwargs)
    return stack, AgentToolSurface(stack.service(), stack.evidence if with_evidence else None)


def _who(stack, user="requester", **kwargs) -> AnalyticsIdentity:
    return stack.verifier().verify(stack.token(user, **kwargs))


def _call(surface, identity, tool, **arguments):
    return surface.call(identity, {"tool": tool, "arguments": arguments})


def _analyze(surface, identity, key="tool-key-0001", text=QUESTION):
    return _call(surface, identity, "analytics.analyze", purpose=PURPOSE, request_text=text, idempotency_key=key)


# ---- the catalogue is strict, documented, and pinned ----


def test_the_catalogue_describes_every_tool_with_a_strict_schema():
    entries = {entry["name"]: entry for entry in contract.catalog()}
    assert set(entries) == set(contract.ARGUMENT_MODELS) == {spec.name for spec in contract.TOOLS}
    assert set(entries) == {
        "analytics.analyze",
        "analytics.status",
        "analytics.clarify",
        "analytics.review",
        "analytics.evidence",
    }
    for entry in entries.values():
        assert entry["arguments"]["additionalProperties"] is False, entry["name"]
        assert entry["description"] and entry["title"] and "purpose" in entry["arguments"]["required"]
    assert [e["name"] for e in entries.values() if e["human_only"]] == ["analytics.review"]
    assert entries["analytics.review"]["effect"] == "decision"
    assert {e["name"] for e in entries.values() if e["requires_idempotency_key"]} == {"analytics.analyze"}
    assert {e["name"] for e in entries.values() if e["effect"] == "read"} == {"analytics.status", "analytics.evidence"}


def test_the_catalogue_digest_is_pinned_and_the_document_is_generated_from_it():
    lock = json.loads(catalogue_module.LOCK.read_text())
    assert lock == catalogue_module.lock_payload(), (
        "the tool schemas changed: regenerate with `python -m app.agent_tools.catalogue --write` and bump "
        "TOOL_CATALOG_VERSION"
    )
    assert lock["catalog_version"] == contract.TOOL_CATALOG_VERSION == "agent-tools-v1"
    assert catalogue_module.DOC.read_text() == catalogue_module.render_doc()
    assert contract.catalog_digest() == lock["schema_digest"]
    assert "analytics.review" in catalogue_module.DOC.read_text() and "Human only" in catalogue_module.DOC.read_text()


def test_changing_a_schema_changes_the_digest(monkeypatch):
    before = contract.catalog_digest()
    monkeypatch.setattr(contract.AnalyzeArgs, "model_json_schema", classmethod(lambda cls, *a, **k: {"changed": True}))
    assert contract.catalog_digest() != before


# ---- arguments are strict and never echoed ----


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("analytics.analyze", {"purpose": PURPOSE, "request_text": QUESTION}),  # no idempotency key
        ("analytics.analyze", {"purpose": PURPOSE, "request_text": QUESTION, "idempotency_key": "short"}),
        ("analytics.analyze", {"purpose": PURPOSE, "request_text": "x" * 2_001, "idempotency_key": "tool-key-0001"}),
        (
            "analytics.analyze",
            {"purpose": PURPOSE, "request_text": QUESTION, "idempotency_key": "tool-key-0001", "sql": "DROP"},
        ),
        ("analytics.status", {"purpose": PURPOSE, "run_id": "../../etc/passwd"}),
        ("analytics.status", {"purpose": PURPOSE}),
        ("analytics.clarify", {"purpose": PURPOSE, "run_id": "r1", "ambiguity_code": "everything", "selected_id": "x"}),
        ("analytics.review", {"purpose": PURPOSE, "run_id": "r1", "decision": "maybe", "plan_fingerprint": "f" * 64}),
        ("analytics.review", {"purpose": PURPOSE, "run_id": "r1", "decision": "approved", "plan_fingerprint": "short"}),
        ("analytics.evidence", {"purpose": PURPOSE, "run_id": "r1", "include_rows": True}),
    ],
)
def test_invalid_arguments_are_rejected_without_echoing_them(tmp_path, tool, arguments):
    stack, surface = _surface(tmp_path)
    result = _call(surface, _who(stack), tool, **arguments)
    assert not result.ok and result.error.code == "invalid_arguments" and result.error.status == 422
    dumped = result.model_dump_json()
    assert "passwd" not in dumped and "DROP" not in dumped and "xxxx" not in dumped


def test_unknown_tools_and_malformed_calls_are_refused(tmp_path):
    stack, surface = _surface(tmp_path)
    who = _who(stack)
    assert surface.call(who, {"tool": "analytics.run_sql", "arguments": {}}).error.code == "unknown_tool"
    assert surface.call(who, {"tool": "analytics.run_sql; DROP", "arguments": {}}).error.status == 404
    for bad in ({}, {"tool": ""}, {"tool": "analytics.status", "arguments": {}, "extra": 1}, "nope", None):
        assert surface.call(who, bad).error.code == "invalid_tool_call"


# ---- analyze, status, idempotency, scope ----


def test_a_tool_call_returns_the_same_governed_outcome_as_the_service(tmp_path):
    stack, surface = _surface(tmp_path)
    who = _who(stack)
    via_tool = _analyze(surface, who)
    assert via_tool.ok and via_tool.run.state == "terminal" and via_tool.run.outcome.outcome == "answer"
    via_service = stack.service().analyze(who, purpose=PURPOSE, idempotency_key="tool-key-0001", request_text=QUESTION)
    assert via_service.run_id == via_tool.run.run_id  # the same key is the same run on either surface
    assert via_service.outcome.result == via_tool.run.outcome.result
    status = _call(surface, who, "analytics.status", purpose=PURPOSE, run_id=via_tool.run.run_id)
    assert status.ok and status.run.outcome.result == via_tool.run.outcome.result


def test_idempotency_is_enforced_exactly_as_for_rest(tmp_path):
    stack, surface = _surface(tmp_path)
    who = _who(stack)
    first = _analyze(surface, who)
    again = _analyze(surface, who)
    assert again.run.run_id == first.run.run_id
    reused = _analyze(surface, who, text="Show monthly orders instead")
    assert not reused.ok and (reused.error.code, reused.error.status) == ("idempotency_key_reused", 409)
    other_key = _analyze(surface, who, key="tool-key-0002")
    assert other_key.run.run_id != first.run.run_id


def test_purpose_tenant_and_run_scope_fail_closed(tmp_path):
    stack, surface = _surface(tmp_path)
    who = _who(stack)
    run_id = _analyze(surface, who).run.run_id
    wrong_purpose = _call(surface, who, "analytics.status", purpose="billing", run_id=run_id)
    assert (wrong_purpose.error.code, wrong_purpose.error.status) == ("purpose_not_authorized", 403)
    foreign = _who(stack, "outsider", tenant="tenant-b")
    assert _call(surface, foreign, "analytics.status", purpose=PURPOSE, run_id=run_id).error.code == "run_not_found"
    assert _call(surface, foreign, "analytics.evidence", purpose=PURPOSE, run_id=run_id).error.code == "run_not_found"
    assert _call(surface, who, "analytics.status", purpose=PURPOSE, run_id="no-such-run").error.status == 404
    no_purpose = _who(stack, "narrow", purposes=())
    assert _analyze(surface, no_purpose).error.code == "purpose_not_authorized"


# ---- clarify ----


def test_clarification_is_bound_to_the_original_requester(tmp_path):
    stack, surface = _surface(tmp_path, ambiguous=True)
    who = _who(stack)
    paused = _analyze(surface, who)
    assert paused.run.state == "waiting_clarification"
    question = paused.run.outcome.questions[0]
    arguments = dict(
        purpose=PURPOSE, run_id=paused.run.run_id, ambiguity_code=question.id, selected_id=question.choices[0].id
    )
    intruder = _call(surface, _who(stack, "intruder"), "analytics.clarify", **arguments)
    assert (intruder.error.code, intruder.error.status) == ("not_run_requester", 403)
    bogus = _call(surface, who, "analytics.clarify", **{**arguments, "selected_id": "not-a-candidate"})
    assert (bogus.error.code, bogus.error.status) == ("invalid_clarification", 422)
    assert _call(surface, who, "analytics.clarify", **arguments).ok


# ---- review is human-only and keeps separation of duties ----


def _paused(tmp_path):
    stack, surface = _surface(tmp_path, review_threshold=1e-9)
    requester = _who(stack)
    paused = _analyze(surface, requester)
    assert paused.run.state == "waiting_review"
    review = stack.control.get_review(paused.run.outcome.review_id, tenant_id="tenant-a", purpose=PURPOSE)
    return stack, surface, requester, paused.run.run_id, review.plan_fingerprint


def test_a_human_reviewer_decides_and_the_requester_cannot_approve_their_own_run(tmp_path):
    stack, surface, requester, run_id, fingerprint = _paused(tmp_path)
    decision = dict(purpose=PURPOSE, run_id=run_id, decision="approved", plan_fingerprint=fingerprint)
    own = _call(surface, requester, "analytics.review", **decision)
    assert (own.error.code, own.error.status) == ("review_not_permitted", 403)
    stale = _call(surface, _who(stack, "reviewer"), "analytics.review", **{**decision, "plan_fingerprint": "0" * 64})
    assert (stale.error.code, stale.error.status) == ("review_stale", 409)
    approved = _call(surface, _who(stack, "reviewer"), "analytics.review", **decision)
    assert approved.ok and approved.run.outcome.outcome == "answer"
    again = _call(surface, _who(stack, "reviewer"), "analytics.review", **decision)
    assert again.error.code == "run_not_awaiting_review"


@pytest.mark.parametrize(
    "identity",
    [
        AnalyticsIdentity(tenant_id="tenant-a", user_id="agent:planner", purposes=[PURPOSE]),
        AnalyticsIdentity(tenant_id="tenant-a", user_id="system:release-bot", purposes=[PURPOSE]),
        AnalyticsIdentity(tenant_id="tenant-a", user_id="service:etl", purposes=[PURPOSE]),
        AnalyticsIdentity(tenant_id="tenant-a", user_id="model:gpt", purposes=[PURPOSE]),
        AnalyticsIdentity(tenant_id="tenant-a", user_id="reviewer", purposes=[PURPOSE], claims={"act_sub": "agent-7"}),
        AnalyticsIdentity(tenant_id="tenant-a", user_id="reviewer", purposes=[PURPOSE], claims={"delegated_by": "u1"}),
    ],
)
def test_agents_and_delegated_callers_can_never_decide_a_review(tmp_path, identity):
    stack, surface, _, run_id, fingerprint = _paused(tmp_path)
    decision = dict(purpose=PURPOSE, run_id=run_id, decision="approved", plan_fingerprint=fingerprint)
    refused = _call(surface, identity, "analytics.review", **decision)
    assert (refused.error.code, refused.error.status) == ("human_required", 403)
    rejected = _call(surface, identity, "analytics.review", **{**decision, "decision": "rejected"})
    assert rejected.error.code == "human_required"
    still = _call(surface, _who(stack), "analytics.status", purpose=PURPOSE, run_id=run_id)
    assert still.run.state == "waiting_review"  # nothing moved


def test_caller_kind_separates_direct_humans_from_agents():
    human = AnalyticsIdentity(tenant_id="t", user_id="alice", purposes=["p"])
    assert caller_kind(human) == "human"
    for user in ("agent:x", "system:x", "model:x", "service:x"):
        assert caller_kind(human.model_copy(update={"user_id": user})) == "agent"
    for claim in ("act_sub", "azp_agent", "delegated_by"):
        assert caller_kind(human.model_copy(update={"claims": {claim: "someone"}})) == "agent"
    assert caller_kind(human.model_copy(update={"claims": {"act_sub": ""}})) == "human"


def test_agents_keep_every_non_decision_tool(tmp_path):
    stack, surface = _surface(tmp_path)
    agent = AnalyticsIdentity(tenant_id="tenant-a", user_id="agent:planner", purposes=[PURPOSE])
    answered = _analyze(surface, agent)
    assert answered.ok and answered.run.outcome.outcome == "answer"
    assert _call(surface, agent, "analytics.status", purpose=PURPOSE, run_id=answered.run.run_id).ok
    assert _call(surface, agent, "analytics.evidence", purpose=PURPOSE, run_id=answered.run.run_id).ok


# ---- evidence ----


def test_the_evidence_tool_returns_a_data_free_summary_that_matches_the_sealed_envelope(tmp_path):
    stack, surface = _surface(tmp_path)
    who = _who(stack)
    run_id = _analyze(surface, who).run.run_id
    summary = _call(surface, who, "analytics.evidence", purpose=PURPOSE, run_id=run_id)
    assert summary.ok and summary.run is None
    evidence = summary.evidence
    envelope = stack.evidence.get(run_id, tenant_id="tenant-a", purpose=PURPOSE)
    assert evidence.envelope_id == envelope.envelope_id and evidence.content_fingerprint == envelope.content_fingerprint
    assert (evidence.chain_seq, evidence.chain_hash) == stack.evidence.seal_position(
        run_id, tenant_id="tenant-a", purpose=PURPOSE
    )
    assert evidence.terminal_kind == "succeeded" and evidence.policy_effect == "allow"
    assert evidence.validation_status in {"valid", "valid_with_warnings"} and evidence.row_count > 0
    assert evidence.result_fingerprint == envelope.result.result_fingerprint
    assert evidence.semantic_contract == "sales-core@v1" and evidence.transition_count == len(envelope.transitions)
    dumped = summary.model_dump_json().lower()
    for forbidden in ("select ", "sales_orders", "policy_values", "request_text", "rows", "created_at"):
        assert forbidden not in dumped, forbidden
    assert "evidence" in json.loads(summary.model_dump_json())


def test_evidence_needs_a_terminal_sealed_run_and_a_configured_store(tmp_path):
    stack, surface, requester, run_id, _ = _paused(tmp_path / "paused")
    waiting = _call(surface, requester, "analytics.evidence", purpose=PURPOSE, run_id=run_id)
    assert (waiting.error.code, waiting.error.status) == ("run_not_terminal", 409)
    stack2, bare = _surface(tmp_path, "bare", with_evidence=False)
    done = _analyze(bare, _who(stack2))
    assert (
        _call(bare, _who(stack2), "analytics.evidence", purpose=PURPOSE, run_id=done.run.run_id).error.code
        == "evidence_not_configured"
    )
    with pytest.raises(EvidenceNotFoundError):
        stack.evidence.seal_position("no-such-run", tenant_id="tenant-a", purpose=PURPOSE)


def test_a_refused_run_has_evidence_without_result_fields(tmp_path):
    stack, surface = _surface(tmp_path, denied=True)
    who = _who(stack)
    refused = _analyze(surface, who)
    assert refused.run.outcome.outcome == "refuse"
    evidence = _call(surface, who, "analytics.evidence", purpose=PURPOSE, run_id=refused.run.run_id).evidence
    assert evidence.terminal_kind == "refused" and "policy_denied" in evidence.error_codes
    assert evidence.result_fingerprint is None and evidence.row_count is None


# ---- failures never leak ----


def test_unexpected_errors_become_internal_error_without_their_text(tmp_path, monkeypatch):
    stack, surface = _surface(tmp_path)
    who = _who(stack)

    def boom(*args, **kwargs):
        raise RuntimeError("SELECT secret FROM vault -- password=hunter2")

    monkeypatch.setattr(surface.service, "status", boom)
    result = _call(surface, who, "analytics.status", purpose=PURPOSE, run_id="r1")
    assert (result.error.code, result.error.status) == ("internal_error", 500)
    assert "hunter2" not in result.model_dump_json() and "SELECT" not in result.model_dump_json()


# ---- the surface is inert and adds no transport ----


def test_nothing_mounts_the_tool_surface_yet():
    for path in (SERVICE / "app/main.py", SERVICE / "app/api_v2.py"):
        assert "agent_tools" not in path.read_text(), path.name
    body = (SERVICE / "app/agent_tools/dispatcher.py").read_text()
    assert "fastapi" not in body.lower() and "FastAPI" not in body  # transport adapters (MCP) are ADS-061
