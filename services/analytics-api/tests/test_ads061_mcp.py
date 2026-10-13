"""ADS-061: the MCP adapter cannot bypass API authorization, the governed graph, or audit boundaries."""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from jose import jwt
from reference_stack.stack import build_stack

from app.agent_tools import AgentToolSurface, ToolAudit
from app.analysis_artifacts import artifact_for_run
from app.mcp import PROTOCOL_VERSION, McpAdapter, mcp_name, serve_lines
from app.security import IdentityResolver, InMemoryGroupDirectory
from packages.platform_contracts import agent_tools as contract
from packages.platform_contracts.analytics_v2_api import AnalyzeRunResponse
from packages.platform_contracts.delegation import AgentGrant, DelegationPolicy

SERVICE = Path(__file__).resolve().parent.parent
PURPOSE, QUESTION = "analytics", "Show monthly revenue"
URL = "/api/v2/analytics"
POLICY = DelegationPolicy(
    policy_version="test",
    grants=(AgentGrant(agent_id="agent-planner", purposes=("analytics",)),),
    approval={"status": "approved", "approved_by": "test-harness", "approved_at": "2026-10-13"},
)


def _rig(tmp_path, name="a", **stack_kwargs):
    stack = build_stack("duckdb", tmp_path / name, **stack_kwargs)
    directory = InMemoryGroupDirectory()
    for user in ("requester", "reviewer", "outsider"):
        directory.set_user("tenant-a", user, ("analyst",))
    resolver = IdentityResolver(stack.verifier(), directory=directory, delegation=POLICY)
    audit = ToolAudit()
    surface = AgentToolSurface(stack.service(), stack.evidence, audit)
    return stack, directory, audit, McpAdapter(surface, resolver)


def _rpc(method, params=None, id=1):
    message = {"jsonrpc": "2.0", "method": method}
    if id is not None:
        message["id"] = id
    if params is not None:
        message["params"] = params
    return message


def _call(adapter, token, tool, **arguments):
    return adapter.handle(token, _rpc("tools/call", {"name": mcp_name(tool), "arguments": arguments}))


def _structured(response):
    return response["result"]["structuredContent"]


def _analyze(adapter, token, key="mcp-key-0001", text=QUESTION):
    return _call(adapter, token, "analytics.analyze", purpose=PURPOSE, request_text=text, idempotency_key=key)


def _delegated_token(stack, user="reviewer"):
    claims = {
        "iss": stack.verifier().issuer,
        "aud": stack.verifier().audience,
        "sub": user,
        "tid": "tenant-a",
        "groups": ["analyst"],
        "purposes": ["analytics"],
        "act": {"sub": "agent-planner"},
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return jwt.encode(claims, stack.secret, algorithm="HS256", headers={"kid": next(iter(stack.verifier().jwks))})


# ---- protocol ----


def test_the_adapter_speaks_the_protocol_subset_it_advertises(tmp_path):
    stack, _, _, adapter = _rig(tmp_path)
    token = stack.token("requester")
    init = adapter.handle(token, _rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}}))
    assert init["id"] == 1 and init["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert adapter.handle(token, _rpc("ping"))["result"] == {}
    assert adapter.handle(token, _rpc("notifications/initialized", id=None)) is None
    unknown = adapter.handle(token, _rpc("resources/list"))
    assert unknown["error"]["code"] == -32601
    assert adapter.handle(token, "{not json")["error"]["code"] == -32700
    for bad in (
        '[{"jsonrpc":"2.0","id":1,"method":"ping"}]',
        '{"id":1,"method":"ping"}',
        '"text"',
        '{"jsonrpc":"2.0","id":1.5,"method":"ping"}',
        '{"jsonrpc":"2.0","id":1,"method":7}',
    ):
        assert adapter.handle(token, bad)["error"]["code"] == -32600, bad
    assert adapter.handle(token, "x" * 70_000)["error"]["code"] == -32600
    assert adapter.handle(token, _rpc("tools/list", params="nope"))["error"]["code"] == -32602


def test_tools_list_mirrors_the_catalogue_with_mcp_names_and_hints(tmp_path):
    stack, _, _, adapter = _rig(tmp_path)
    tools = adapter.handle(stack.token("requester"), _rpc("tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == [mcp_name(s.name) for s in contract.TOOLS]
    assert all("." not in t["name"] for t in tools)
    for tool, spec in zip(tools, contract.TOOLS, strict=True):
        assert tool["inputSchema"] == contract.ARGUMENT_MODELS[spec.name].model_json_schema()
        assert tool["inputSchema"]["additionalProperties"] is False and tool["description"] == spec.description
        assert (
            tool["annotations"]["readOnlyHint"] == (spec.effect == "read")
            and tool["annotations"]["destructiveHint"] is False
        )


# ---- authentication on every message ----


def test_every_message_needs_a_valid_token_and_changes_in_the_directory_apply_to_the_next_message(tmp_path):
    stack, directory, audit, adapter = _rig(tmp_path)
    token = stack.token("requester")
    assert "result" in adapter.handle(token, _rpc("ping"))
    for bad in (None, "", "garbage", stack.token("requester", ttl_minutes=-5), stack.token("stranger")):
        response = adapter.handle(bad, _rpc("tools/list"))
        assert response["error"]["code"] == -32001 and response["id"] == 1, bad
    assert adapter.handle("garbage", _rpc("notifications/initialized", id=None)) is None  # no reply to anyone
    directory.disable("tenant-a", "requester")
    assert adapter.handle(token, _rpc("ping"))["error"]["code"] == -32001  # same token, next message
    denied = [e for e in audit.events if e.event_type == "tool_call_unauthenticated"]
    assert len(denied) == 7 and all(e.actor_id == "unknown" and e.tenant_id == "unauthenticated" for e in denied)
    assert "garbage" not in json.dumps([e.model_dump(mode="json") for e in audit.events])


# ---- the same governed outcomes as REST ----


def test_an_mcp_call_gives_the_same_governed_outcome_run_and_artifact_as_rest(tmp_path):
    stack, _, _, adapter = _rig(tmp_path)
    token = stack.token("requester")
    via_mcp = _analyze(adapter, token)
    assert via_mcp["result"]["isError"] is False
    run_mcp = AnalyzeRunResponse.model_validate(_structured(via_mcp)["run"])
    rest = TestClient(stack.app()).post(
        f"{URL}/analyze",
        json={"request_text": QUESTION, "purpose": PURPOSE},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "mcp-key-0001"},
    )
    run_rest = AnalyzeRunResponse.model_validate(rest.json())
    assert run_rest.run_id == run_mcp.run_id and run_rest.outcome.result == run_mcp.outcome.result
    identity = stack.verifier().verify(token)
    artifact = artifact_for_run(stack.service(), stack.evidence, identity, purpose=PURPOSE, run_id=run_mcp.run_id)
    again = adapter.handle(
        token,
        _rpc("tools/call", {"name": "analytics_evidence", "arguments": {"purpose": PURPOSE, "run_id": run_mcp.run_id}}),
    )
    assert _structured(again)["evidence"]["content_fingerprint"] == artifact.evidence.content_fingerprint
    text = json.loads(via_mcp["result"]["content"][0]["text"])
    assert text == _structured(via_mcp)


def test_tool_failures_are_tool_errors_with_the_same_codes_not_protocol_errors(tmp_path):
    stack, _, _, adapter = _rig(tmp_path)
    token = stack.token("requester")
    first = _analyze(adapter, token)
    reused = _analyze(adapter, token, text="Show monthly orders instead")
    assert reused["result"]["isError"] is True and _structured(reused)["error"]["code"] == "idempotency_key_reused"
    wrong_purpose = _call(
        adapter, token, "analytics.status", purpose="billing", run_id=_structured(first)["run"]["run_id"]
    )
    assert _structured(wrong_purpose)["error"] == {"code": "purpose_not_authorized", "status": 403}
    bad_args = _call(adapter, token, "analytics.status", purpose=PURPOSE)
    assert _structured(bad_args)["error"]["code"] == "invalid_arguments"
    assert (
        adapter.handle(token, _rpc("tools/call", {"name": "analytics_run_sql", "arguments": {}}))["error"]["code"]
        == -32602
    )
    assert (
        adapter.handle(token, _rpc("tools/call", {"name": "analytics.analyze", "arguments": {}}))["error"]["code"]
        == -32602
    )
    assert (
        adapter.handle(token, _rpc("tools/call", {"name": "analytics_status", "arguments": "x"}))["error"]["code"]
        == -32602
    )


# ---- no bypass ----


def test_identity_can_never_come_from_the_arguments(tmp_path):
    stack, _, _, adapter = _rig(tmp_path)
    token = stack.token("requester")
    for smuggled in (
        {"tenant_id": "tenant-b"},
        {"user_id": "reviewer"},
        {"identity": {"tenant_id": "x"}},
        {"groups": ["admin"]},
    ):
        response = _call(
            adapter,
            token,
            "analytics.analyze",
            purpose=PURPOSE,
            request_text=QUESTION,
            idempotency_key="mcp-key-0002",
            **smuggled,
        )
        assert _structured(response)["error"]["code"] == "invalid_arguments", smuggled


def test_the_adapter_imports_only_the_tool_surface_and_identity_layers():
    tree = ast.parse((SERVICE / "app/mcp/adapter.py").read_text())
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }
    allowed = {
        "__future__",
        "json",
        "collections.abc",
        "typing",
        "app.agent_tools",
        "app.security",
        "packages.platform_contracts.agent_tools",
    }
    assert imported <= allowed, imported - allowed
    for path in (SERVICE / "app/main.py", SERVICE / "app/api_v2.py"):
        assert "app.mcp" not in path.read_text(), path.name  # nothing mounts it yet


def test_review_stays_human_only_and_separated_through_mcp(tmp_path):
    stack, _, _, adapter = _rig(tmp_path, review_threshold=1e-9)
    requester = stack.token("requester")
    paused = _structured(_analyze(adapter, requester))["run"]
    assert paused["state"] == "waiting_review"
    review = stack.control.get_review(paused["outcome"]["review_id"], tenant_id="tenant-a", purpose=PURPOSE)
    decision = dict(
        purpose=PURPOSE, run_id=paused["run_id"], decision="approved", plan_fingerprint=review.plan_fingerprint
    )
    own = _structured(_call(adapter, requester, "analytics.review", **decision))
    assert own["error"]["code"] == "review_not_permitted"
    delegated = _structured(_call(adapter, _delegated_token(stack), "analytics.review", **decision))
    assert delegated["error"]["code"] == "human_required"
    state = _structured(_call(adapter, requester, "analytics.status", purpose=PURPOSE, run_id=paused["run_id"]))
    assert state["run"]["state"] == "waiting_review"
    done = _structured(_call(adapter, stack.token("reviewer"), "analytics.review", **decision))
    assert done["ok"] and done["run"]["outcome"]["outcome"] == "answer"


def test_other_tenants_cannot_reach_a_run_through_mcp(tmp_path):
    stack, directory, _, adapter = _rig(tmp_path)
    run_id = _structured(_analyze(adapter, stack.token("requester")))["run"]["run_id"]
    directory.set_user("tenant-b", "outsider", ("analyst",))
    foreign = stack.token("outsider", tenant="tenant-b")
    for tool in ("analytics.status", "analytics.evidence"):
        assert (
            _structured(_call(adapter, foreign, tool, purpose=PURPOSE, run_id=run_id))["error"]["code"]
            == "run_not_found"
        )


# ---- audit ----


def test_every_call_is_audited_without_argument_values_tokens_or_data(tmp_path):
    stack, _, audit, adapter = _rig(tmp_path)
    token = stack.token("requester")
    ok = _analyze(adapter, token)
    _call(adapter, token, "analytics.status", purpose="billing", run_id="r-unknown-1")  # a refusal is audited too
    _call(adapter, token, "analytics.analyze", purpose=PURPOSE, request_text="x")  # invalid arguments are audited too
    events = [e for e in audit.events if e.event_type == "tool_call"]
    assert [e.payload["tool"] for e in events] == ["analytics.analyze", "analytics.status", "analytics.analyze"]
    assert all(
        e.payload["transport"] == "mcp" and e.actor_id == "requester" and e.tenant_id == "tenant-a" for e in events
    )
    assert [e.payload["ok"] for e in events] == [True, False, False]
    assert [e.payload["error_code"] for e in events] == [None, "purpose_not_authorized", "invalid_arguments"]
    assert all(len(e.payload["arguments_sha256"]) == 64 for e in events)
    assert events[0].payload["run_id_sha256"] and audit.verify()
    dumped = json.dumps([e.model_dump(mode="json") for e in audit.events])
    for forbidden in (
        QUESTION,
        token,
        "mcp-key-0001",
        _structured(ok)["run"]["run_id"],
        "SELECT",
        "sales_orders",
        "revenue",
    ):
        assert forbidden not in dumped, forbidden


def test_the_audit_chain_detects_tampering_and_other_transports_share_it(tmp_path):
    stack, _, audit, adapter = _rig(tmp_path)
    token = stack.token("requester")
    _analyze(adapter, token)
    direct = adapter.surface.call(
        stack.verifier().verify(token),
        {"tool": "analytics.status", "arguments": {"purpose": PURPOSE, "run_id": "none-1"}},
    )
    assert not direct.ok
    assert [e.payload["transport"] for e in audit.events] == ["mcp", "direct"]
    assert audit.verify()
    audit.chain.events[0].payload["ok"] = False  # rewrite history
    assert not audit.verify()


# ---- the stdio framing ----


def test_line_framing_returns_one_line_per_request_and_never_echoes_the_token(tmp_path):
    stack, _, _, adapter = _rig(tmp_path)
    token = stack.token("requester")
    lines = [
        json.dumps(_rpc("initialize", {"protocolVersion": PROTOCOL_VERSION})),
        json.dumps(_rpc("notifications/initialized", id=None)),
        "",
        json.dumps(_rpc("tools/list", id=2)),
        "not json",
    ]
    out = list(serve_lines(adapter, token, lines))
    assert len(out) == 3 and [json.loads(o).get("id") for o in out] == [1, 2, None]
    assert json.loads(out[2])["error"]["code"] == -32700 and token not in "".join(out)
    assert list(serve_lines(adapter, "bad", [json.dumps(_rpc("ping"))])) == [
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32001,"message":"unauthenticated"}}'
    ]
