"""ADS-048: the local reference stack runs both smoke journeys with fakes only."""

from __future__ import annotations

import socket

import duckdb
import pytest
from fastapi.testclient import TestClient
from reference_stack.__main__ import main
from reference_stack.fakes import ScriptedIntentClient, seed_lake
from reference_stack.smoke import run_all, run_journey
from reference_stack.stack import build_stack


@pytest.fixture
def no_network(monkeypatch):
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("the reference stack must not open network connections")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    return attempts


def test_both_smoke_journeys_pass_without_any_network_connection(no_network):
    report = run_all()
    failed = [(j["engine"], s["name"], s["detail"]) for j in report["journeys"] for s in j["steps"] if not s["ok"]]
    assert report["ok"] and not failed, failed
    assert no_network == []
    assert [j["engine"] for j in report["journeys"]] == ["duckdb", "postgres"]
    names = [[s["name"] for s in j["steps"]] for j in report["journeys"]]
    assert names[0] == names[1] and len(names[0]) == 13  # same journey on both dialects
    assert report["cross_dialect_rows_identical"] is True


def test_journey_covers_the_governed_boundaries():
    steps = {s.name for s in run_journey("duckdb").steps}
    for expected in (
        "unauthenticated request is refused",
        "unauthorized purpose is refused",
        "monthly revenue returns a grounded answer",
        "idempotent replay returns the same run and fingerprint",
        "terminal run is sealed in a verified evidence chain",
        "an unsupported question fails safely without a result",
        "an expensive plan pauses for human review",
        "the requester cannot approve their own plan",
    ):
        assert expected in steps


def test_postgres_journey_uses_the_real_gateway_against_an_emulated_server(tmp_path):
    stack = build_stack("postgres", tmp_path)
    client = TestClient(stack.app())
    response = client.post(
        "/api/v2/analytics/analyze",
        json={"request_text": "Show monthly revenue", "purpose": "analytics"},
        headers={"Authorization": f"Bearer {stack.token('requester')}", "Idempotency-Key": "key-00000001"},
    )
    assert response.json()["outcome"]["outcome"] == "answer"
    engine = stack.gateway._engine
    assert "SET TRANSACTION READ ONLY" in engine.session_statements
    assert any(s.startswith("SET LOCAL statement_timeout") for s in engine.session_statements)
    assert engine.executed_sql and all("DATE_TRUNC" in s or "SUM" in s for s in engine.executed_sql)
    assert engine.rollbacks >= len(engine.executed_sql)  # every transaction rolled back


def test_tokens_are_signed_per_stack_and_not_portable():
    first, second = build_stack("duckdb"), build_stack("duckdb")
    client = TestClient(first.app())
    body = {"request_text": "Show monthly revenue", "purpose": "analytics"}
    foreign = client.post(
        "/api/v2/analytics/analyze",
        json=body,
        headers={"Authorization": f"Bearer {second.token('requester')}", "Idempotency-Key": "key-00000001"},
    )
    assert foreign.status_code == 401


def test_seed_is_deterministic_and_the_scripted_model_is_schema_bound(tmp_path):
    def digest(path):
        connection = duckdb.connect()
        return connection.execute(
            f"SELECT COUNT(*), SUM(amount), MIN(created_at), MAX(created_at) FROM read_parquet('{path}')"
        ).fetchall()

    first, second = digest(seed_lake(tmp_path / "a")), digest(seed_lake(tmp_path / "b"))
    assert first == second
    assert first[0][0] == 100 and first[0][1] == 5050
    client = ScriptedIntentClient("req-1")
    assert client.complete_json(prompt='Request: "tell me a joke"', schema={}, max_tokens=1) == {
        "unsupported_request": True
    }
    assert (
        client.complete_json(prompt='Request: "revenue by status"', schema={}, max_tokens=1)["group_by"][0][
            "dimension_id"
        ]
        == "status"
    )


def test_cli_smoke_exits_zero_and_reports(capsys):
    assert main(["smoke", "--engine", "duckdb"]) == 0
    out = capsys.readouterr().out
    assert "[PASS] duckdb" in out and "RESULT: PASS" in out


def test_the_reference_stack_never_wires_the_production_app():
    from app import main as production

    run_journey("duckdb")
    assert production.v2_runtime.service is None and production.v2_runtime.verifier is None
