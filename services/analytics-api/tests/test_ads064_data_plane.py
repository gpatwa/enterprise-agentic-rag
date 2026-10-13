"""ADS-064: no result rows or credentials cross the customer-data-plane boundary."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest
from jose import jwt
from pydantic import ValidationError
from reference_stack.fakes import ContractsProvider
from test_ads040_execution_gateways import _contract, _intent

from app.compiler import DuckDBCompilerAdapter
from app.compiler.postgres import CompiledQuery
from app.data_plane import (
    BoundaryViolation,
    ConnectionSpec,
    ControlPlaneClient,
    DataPlaneAgent,
    DataPlaneError,
    Scanner,
    VpcBoundary,
    sign,
)
from app.data_plane.boundary import CLIENT_IN, CONTROL_IN, CONTROL_OUT
from app.execution import DuckDBGateway
from app.execution.result_validation import _canonical, plan_fingerprint
from app.security import IdentityResolver, InMemoryGroupDirectory, OIDCVerifier
from app.security.secrets import InMemorySecretProvider
from packages.platform_contracts import data_plane as protocol
from packages.platform_contracts.data_plane import (
    Envelope,
    EstimateRequest,
    EstimateResponse,
    ExecuteRequest,
    ExecuteResponse,
    LimitsMessage,
    plan_digest,
)
from packages.platform_contracts.semantic import SemanticRegistryDocument

SERVICE = Path(__file__).resolve().parent.parent
KEY = b"channel-key-local-test-only"
CREDENTIAL = "CANARY-CRED-9d41c7e2-warehouse-password"
DP_SECRET = "data-plane-issuer-secret"
LIMITS = LimitsMessage(timeout_seconds=10, max_rows=1000, max_bytes=1_000_000, max_cost_units=1e9)
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _lake(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("""CREATE TABLE sales_orders AS SELECT 'o' || i AS id,
        CAST(1000.37 + i * 7.13 AS DECIMAL(12,2)) AS amount,
        CASE WHEN i % 2 = 0 THEN 'refunded' ELSE 'paid' END AS status,
        TIMESTAMP '2024-01-01' + INTERVAL (i) HOUR AS created_at FROM range(1, 61) t(i)""")
    connection.execute(
        """CREATE TABLE order_items AS SELECT 'o' || i AS order_id FROM range(1, 61) t(i), range(1, 4) u(k)"""
    )
    for table in ("sales_orders", "order_items"):
        connection.execute(f"COPY {table} TO '{tmp_path / (table + '.parquet')}' (FORMAT PARQUET)")
    oracle = connection.execute(
        "SELECT status, SUM(amount) FROM sales_orders WHERE status IN ('paid','refunded') GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    connection.close()
    return {t: tmp_path / f"{t}.parquet" for t in ("sales_orders", "order_items")}, oracle


def _issuer_token(user="requester", *, tenant="tenant-a", purposes=("analytics",), secret=DP_SECRET, aud="data-plane"):
    claims = {
        "iss": "https://dp.example",
        "aud": aud,
        "sub": user,
        "tid": tenant,
        "groups": ["analyst"],
        "purposes": list(purposes),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    return jwt.encode(claims, secret, algorithm="HS256", headers={"kid": "dp-key"})


def _rig(tmp_path, *, agent_cls=DataPlaneAgent, factory=None, scanner=None):
    sources, oracle = _lake(tmp_path)
    clock = Clock()
    contract = _contract()
    contracts = ContractsProvider(SemanticRegistryDocument(lifecycle="certified", contract=contract))
    directory = InMemoryGroupDirectory()
    for user in ("requester", "colleague"):
        directory.set_user("tenant-a", user, ("analyst",))
    directory.set_user("tenant-b", "requester", ("analyst",))
    resolver = IdentityResolver(
        OIDCVerifier("https://dp.example", "data-plane", {"dp-key": DP_SECRET}, algorithms=("HS256",)),
        directory=directory,
    )

    def default_factory(secret: str):
        assert secret == CREDENTIAL  # the credential reaches the factory inside the data plane, and only there
        return DuckDBGateway(sources, allowed_root=tmp_path)

    agent = agent_cls(
        connections={"warehouse-a": ConnectionSpec("tenant-a", "duckdb", "warehouse", factory or default_factory)},
        secrets_provider=InMemorySecretProvider({("tenant-a", "warehouse"): (CREDENTIAL, "v1")}),
        contracts=contracts,
        compilers={"duckdb": DuckDBCompilerAdapter()},
        client_resolver=resolver,
        channel_key=KEY,
        clock=clock,
    )
    scanner = scanner or Scanner()
    boundary = VpcBoundary(agent, channel_key=KEY, scanner=scanner, clock=clock)
    client = ControlPlaneClient(boundary, tenant_id="tenant-a", connection_alias="warehouse-a")
    intent = _intent(
        time_range=None, filters=[{"field_id": "orders.status", "operator": "in", "values": ["paid", "refunded"]}]
    )
    plan = DuckDBCompilerAdapter().compile(intent, contract)
    # The oracle's data values are what must never cross: the sums, and the credential.
    scanner.register(CREDENTIAL, *[value for _, value in oracle], *[_canonical(value) for _, value in oracle])
    return agent, boundary, client, intent, plan, oracle, clock


def _execute(client, intent, plan, *, run_id="run-1", limits=LIMITS, user="requester"):
    return client.execute(
        run_id=run_id,
        purpose="analytics",
        user_id=user,
        plan=plan,
        intent=intent.model_dump(mode="json"),
        contract_ref="sales-core@v1",
        limits=limits,
    )


# ---- the protocol cannot carry rows or credentials ----


def test_no_control_path_message_has_a_field_that_could_hold_rows_or_a_credential():
    forbidden_words = ("row", "cell", "password", "secret", "token", "credential", "key", "dsn", "connection_string")
    for model in (
        EstimateRequest,
        ExecuteRequest,
        EstimateResponse,
        ExecuteResponse,
        protocol.PlanEnvelope,
        protocol.DeliveryHandle,
        protocol.ValidationVerdict,
        Envelope,
    ):
        for name in model.model_fields:
            if name in {"row_count"}:
                continue
            assert not any(word in name.lower() for word in forbidden_words), (model.__name__, name)
    assert set(ExecuteResponse.model_fields) == {
        "protocol",
        "message_id",
        "status",
        "error_code",
        "columns",
        "row_count",
        "byte_count",
        "truncated",
        "truncation_reason",
        "estimated_cost_units",
        "elapsed_ms",
        "result_fingerprint",
        "validation",
        "delivery",
    }
    with pytest.raises(ValidationError):
        ExecuteResponse.model_validate({"message_id": "m-0000001", "status": "ok", "rows": [[1, 2]]})
    with pytest.raises(ValidationError):
        EstimateRequest.model_validate({**_minimal_estimate(), "password": "x"})
    assert "rows" in protocol.FetchResponse.model_fields  # rows exist only on the client-path response


def _minimal_estimate():
    envelope = protocol.PlanEnvelope(dialect="duckdb", sql="SELECT 1 FROM sales_orders")
    return {
        "message_id": "m-0000001",
        "tenant_id": "t",
        "run_id": "r",
        "connection_alias": "warehouse-a",
        "plan": envelope.model_dump(),
        "plan_fingerprint": plan_digest(envelope),
    }


def test_the_plan_fingerprint_both_planes_compute_matches_the_result_validation_fingerprint(tmp_path):
    *_, plan, _, _ = _rig(tmp_path)
    envelope = ControlPlaneClient.envelope(plan)
    assert plan_digest(envelope) == plan_fingerprint(plan)
    assert plan_digest(envelope) == plan_digest(
        protocol.PlanEnvelope(dialect="duckdb", sql=plan.sql, parameters=dict(plan.parameters))
    )


# ---- an honest run: metadata across, rows only to the user ----


def test_an_execution_returns_metadata_and_a_verdict_while_rows_go_only_to_the_user(tmp_path):
    agent, boundary, client, intent, plan, oracle, _ = _rig(tmp_path)
    estimate = client.estimate(run_id="run-1", plan=plan)
    assert estimate.status == "ok" and estimate.estimated_cost_units > 0
    response = _execute(client, intent, plan)
    assert response.status == "ok" and response.row_count == 2 and not response.truncated
    assert response.validation.status == "valid" and response.validation.issue_codes == ()
    assert response.columns == ("dimension_0", "metric_0") and response.delivery.row_count == 2
    # The control-plane log holds neither a row value nor the credential.
    control = boundary.log.control_text()
    assert CREDENTIAL not in control and not boundary.log.violations
    for _, total in oracle:
        assert str(total) not in control
    # The rows come from the data plane to the user, and they are the real ones.
    fetched = boundary.fetch(response.delivery.handle_id, _issuer_token())
    assert [tuple(row) for row in fetched.rows] == [(status, _canonical(total)) for status, total in oracle]
    client_log = boundary.log.text(CLIENT_IN)
    assert all(_canonical(total) in client_log for _, total in oracle)
    assert all(str(total) not in boundary.log.text(CONTROL_OUT, CONTROL_IN) for _, total in oracle)


def test_the_data_plane_computes_the_same_result_fingerprint_a_direct_run_would(tmp_path):
    agent, boundary, client, intent, plan, _, _ = _rig(tmp_path)
    sources, _ = _lake(tmp_path / "direct")
    from app.execution import ExecutionLimits
    from app.execution.result_validation import result_fingerprint

    direct = DuckDBGateway(sources, allowed_root=tmp_path / "direct").execute(plan, limits=ExecutionLimits())
    assert _execute(client, intent, plan).result_fingerprint == result_fingerprint(direct)


# ---- the boundary scanner is a real oracle: a leaking agent is blocked and recorded ----


class RowLeakingAgent(DataPlaneAgent):
    def _execute(self, request, now):  # noqa: ANN001
        response = super()._execute(request, now)
        stored = next(iter(self._results.values()))
        return response.model_copy(update={"status": "error", "error_code": f"rows={stored.rows}"})


class CredentialLeakingAgent(DataPlaneAgent):
    """A careless agent that reports the failure text (which quotes the credential) instead of a code."""

    def handle(self, envelope):  # noqa: ANN001
        model = EstimateResponse if envelope.kind == "estimate" else ExecuteResponse
        return model(
            message_id=envelope.message_id, status="error", error_code=f"auth failed for {CREDENTIAL}"
        ).model_dump_json()


def test_a_row_leaking_agent_is_blocked_and_recorded(tmp_path):
    _, boundary, client, intent, plan, _, _ = _rig(tmp_path, agent_cls=RowLeakingAgent)
    with pytest.raises(BoundaryViolation) as caught:
        _execute(client, intent, plan)
    assert caught.value.direction == CONTROL_IN and boundary.log.violations
    assert "1" not in str(caught.value) or "forbidden value" in str(caught.value)
    assert all(total not in str(caught.value) for total in ("7", "CANARY"))  # the error names no content


def test_a_credential_leaking_agent_is_blocked_and_recorded(tmp_path):
    _, boundary, client, intent, plan, _, _ = _rig(tmp_path, agent_cls=CredentialLeakingAgent)
    with pytest.raises(BoundaryViolation):
        client.estimate(run_id="run-1", plan=plan)
    assert boundary.log.violations and CREDENTIAL not in str(boundary.log.violations)


def test_an_oversized_message_is_a_violation(tmp_path):
    _, boundary, client, intent, plan, _, _ = _rig(tmp_path)
    huge = CompiledQuery(sql="SELECT 1 FROM sales_orders -- " + "x" * 70_000, parameters={}, dialect="duckdb")
    with pytest.raises(ValidationError):  # the contract's own size bound stops it before the boundary
        client.estimate(run_id="run-1", plan=huge)


def test_failures_inside_the_data_plane_report_codes_never_text(tmp_path):
    def broken(secret):  # a driver error that would quote the credential
        raise ConnectionError(f"could not log in with {secret}")

    _, boundary, client, intent, plan, _, _ = _rig(tmp_path, factory=broken)
    response = _execute(client, intent, plan)
    assert (response.status, response.error_code) == ("error", "connection_unavailable")
    assert CREDENTIAL not in boundary.log.control_text() and not boundary.log.violations


# ---- the channel is authenticated, fresh, and replay-proof ----


def _forge(
    body: ExecuteRequest | EstimateRequest, *, key=KEY, issued_at=NOW, kind="estimate", message_id=None, tamper=None
):
    text = body.model_dump_json()
    message_id = message_id or body.message_id
    signature = sign(key, message_id=message_id, issued_at=issued_at, kind=kind, body=text)
    return Envelope(
        message_id=message_id,
        issued_at=issued_at,
        kind=kind,
        body=tamper(text) if tamper else text,
        signature=signature,
    )


def test_unsigned_forged_tampered_stale_and_replayed_messages_are_refused(tmp_path):
    agent, boundary, client, intent, plan, _, clock = _rig(tmp_path)
    request = EstimateRequest.model_validate(_estimate_for(plan))
    ok = boundary.send(request)
    assert ok.status == "ok"
    replay = boundary.send(request)  # the same message ID again
    assert replay.error_code == "replayed_message"
    wrong_key = boundary.send_envelope(
        _forge(request.model_copy(update={"message_id": "m-wrongkey1"}), key=b"other"), EstimateResponse
    )
    assert wrong_key.error_code == "bad_signature"
    tampered = boundary.send_envelope(
        _forge(
            request.model_copy(update={"message_id": "m-tamper001"}),
            tamper=lambda t: t.replace("sales_orders", "order_items"),
        ),
        EstimateResponse,
    )
    assert tampered.error_code == "bad_signature"
    stale = boundary.send_envelope(
        _forge(request.model_copy(update={"message_id": "m-stale0001"}), issued_at=NOW - timedelta(minutes=30)),
        EstimateResponse,
    )
    assert stale.error_code == "stale_message"
    garbled = boundary.send_envelope(
        _forge(request.model_copy(update={"message_id": "m-garbled01"}), tamper=lambda t: t[:-5]), EstimateResponse
    )
    assert garbled.error_code == "bad_signature"
    clock.now += timedelta(minutes=10)  # time passes: an old signed message cannot be replayed later either
    late = boundary.send_envelope(_forge(request.model_copy(update={"message_id": "m-late00001"})), EstimateResponse)
    assert late.error_code == "stale_message"


def _estimate_for(source_plan, **overrides):
    envelope = ControlPlaneClient.envelope(source_plan)
    return {
        "message_id": "m-honest001",
        "tenant_id": "tenant-a",
        "run_id": "run-1",
        "connection_alias": "warehouse-a",
        "plan": envelope.model_dump(),
        "plan_fingerprint": plan_digest(envelope),
        **overrides,
    }


def test_a_request_must_name_a_known_connection_for_its_own_tenant_and_dialect_with_an_honest_fingerprint(tmp_path):
    agent, boundary, client, intent, plan, _, _ = _rig(tmp_path)
    cases = {
        "unknown_connection": _estimate_for(plan, message_id="m-unknown01", connection_alias="warehouse-z"),
        "tenant_mismatch": _estimate_for(plan, message_id="m-tenant001", tenant_id="tenant-b"),
        "plan_fingerprint_mismatch": _estimate_for(plan, message_id="m-fprint001", plan_fingerprint="0" * 64),
    }
    for code, body in cases.items():
        assert boundary.send(EstimateRequest.model_validate(body)).error_code == code
    postgres = protocol.PlanEnvelope(dialect="postgres", sql=plan.sql, parameters=dict(plan.parameters))
    wrong_dialect = _estimate_for(
        plan, message_id="m-dialect01", plan=postgres.model_dump(), plan_fingerprint=plan_digest(postgres)
    )
    assert boundary.send(EstimateRequest.model_validate(wrong_dialect)).error_code in {
        "dialect_mismatch",
        "plan_fingerprint_mismatch",
    }


# ---- validation happens where the rows are ----


def test_a_fanout_is_caught_by_the_data_plane_and_only_its_codes_cross(tmp_path):
    _, boundary, client, intent, plan, _, _ = _rig(tmp_path)
    fanout = CompiledQuery(
        sql='SELECT d0."status" AS dimension_0, SUM(d0."amount") AS metric_0 FROM "sales_orders" AS d0 '
        "JOIN \"order_items\" AS i ON i.order_id = d0.id WHERE d0.\"status\" IN ('paid', 'refunded') "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 25",
        parameters={},
        dialect="duckdb",
    )
    response = _execute(client, intent, fanout)
    assert response.status == "ok" and response.validation.status == "invalid"
    assert response.validation.issue_codes == ("fanout_suspected",)
    assert not boundary.log.violations  # the sums the fanout produced never crossed either


def test_limits_and_unsafe_queries_are_enforced_in_the_data_plane(tmp_path):
    _, boundary, client, intent, plan, _, _ = _rig(tmp_path)
    tight = LimitsMessage(timeout_seconds=10, max_rows=1, max_bytes=1_000_000, max_cost_units=1e9)
    truncated = _execute(client, intent, plan, limits=tight, run_id="run-2")
    assert (
        truncated.truncated and truncated.truncation_reason == "max_rows" and truncated.validation.status == "invalid"
    )
    costly = LimitsMessage(timeout_seconds=10, max_rows=10, max_bytes=1_000_000, max_cost_units=0.5)
    assert _execute(client, intent, plan, limits=costly, run_id="run-3").error_code == "cost_limit_exceeded"
    unsafe = CompiledQuery(sql="DELETE FROM sales_orders", parameters={}, dialect="duckdb")
    assert _execute(client, intent, unsafe, run_id="run-4").error_code == "query_rejected"
    bad_intent = client.execute(
        run_id="run-5",
        purpose="analytics",
        user_id="requester",
        plan=plan,
        intent={"nonsense": True},
        contract_ref="sales-core@v1",
        limits=LIMITS,
    )
    assert bad_intent.error_code == "request_unusable"
    missing_contract = client.execute(
        run_id="run-6",
        purpose="analytics",
        user_id="requester",
        plan=plan,
        intent=intent.model_dump(mode="json"),
        contract_ref="sales-core@v9",
        limits=LIMITS,
    )
    assert missing_contract.error_code == "request_unusable"


# ---- the client path ----


def test_rows_are_released_only_to_the_requesting_person_with_their_own_valid_token(tmp_path):
    agent, boundary, client, intent, plan, _, clock = _rig(tmp_path)
    handle = _execute(client, intent, plan).delivery.handle_id
    assert len(handle) == 32 and handle not in {"0" * 32}
    for token, code in (
        (_issuer_token("colleague"), "handle_not_found"),  # same tenant, not the requester
        (_issuer_token("requester", tenant="tenant-b"), "handle_not_found"),  # same name, another tenant
        (_issuer_token(purposes=("reporting",)), "handle_not_found"),  # not authorized for the run's purpose
        (_issuer_token(secret="wrong-secret"), "unauthenticated"),
        (_issuer_token(aud="analytics"), "unauthenticated"),  # a control-plane audience is not accepted here
        ("", "unauthenticated"),
    ):
        with pytest.raises(DataPlaneError) as caught:
            boundary.fetch(handle, token)
        assert caught.value.code == code, token
    with pytest.raises(DataPlaneError) as unknown:
        boundary.fetch("f" * 32, _issuer_token())
    assert unknown.value.code == "handle_not_found"  # unknown and not-yours look the same
    assert boundary.fetch(handle, _issuer_token()).rows
    clock.now += timedelta(minutes=11)
    with pytest.raises(DataPlaneError) as expired:
        boundary.fetch(handle, _issuer_token())
    assert expired.value.code == "handle_expired"
    with pytest.raises(DataPlaneError) as gone:
        boundary.fetch(handle, _issuer_token())
    assert gone.value.code == "handle_not_found"


def test_the_users_token_never_travels_on_the_control_path(tmp_path):
    agent, boundary, client, intent, plan, _, _ = _rig(tmp_path)
    token = _issuer_token()
    handle = _execute(client, intent, plan).delivery.handle_id
    boundary.fetch(handle, token)
    assert token not in boundary.log.control_text() and handle not in boundary.log.text(CONTROL_OUT)


# ---- the control-plane client is structurally unable to hold what it must not ----


def test_the_control_plane_client_imports_no_gateway_secret_or_agent_code():
    tree = ast.parse((SERVICE / "app/data_plane/client.py").read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert imported <= {"__future__", "uuid", "typing", "packages.platform_contracts.data_plane"}, imported
    for path in (SERVICE / "app/main.py", SERVICE / "app/api_v2.py"):
        assert "app.data_plane" not in path.read_text(), path.name  # nothing mounts the agent or the simulator yet
