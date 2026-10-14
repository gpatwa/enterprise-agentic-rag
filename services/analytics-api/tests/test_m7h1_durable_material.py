"""M7-H1: compiled plans and policy values are durable, rows are not, and a status read never runs a query."""

from __future__ import annotations

import pytest
from reference_stack.stack import build_stack
from sqlalchemy import text

from app.execution.bridge import ExecutionResultStore
from app.runtime.governed_stages import CompiledPlanStore, PolicyValueStore

PURPOSE = "analytics"


def _run(tmp_path, question="Show monthly revenue", key="durable-key-0001"):
    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    response = stack.service().analyze(who, purpose=PURPOSE, idempotency_key=key, request_text=question)
    return stack, who, response


def test_a_plan_written_by_one_process_is_readable_by_another(tmp_path):
    stack, who, response = _run(tmp_path)
    state = stack.control.load_latest_checkpoint(run_id=response.run_id, tenant_id=who.tenant_id, purpose=PURPOSE)
    fresh = CompiledPlanStore(stack.control.engine)  # a new process: empty memory, same database
    plan = fresh.get(who.tenant_id, response.run_id, state.compiled_plan_reference)
    original = stack.plans.get(who.tenant_id, response.run_id, state.compiled_plan_reference)
    assert (plan.sql, plan.parameters, plan.dialect, plan.applied_filter_ids) == (
        original.sql,
        original.parameters,
        original.dialect,
        original.applied_filter_ids,
    )


def test_plans_and_values_are_scoped_to_the_tenant_and_run(tmp_path):
    stack, who, response = _run(tmp_path)
    state = stack.control.load_latest_checkpoint(run_id=response.run_id, tenant_id=who.tenant_id, purpose=PURPOSE)
    fresh = CompiledPlanStore(stack.control.engine)
    for tenant, run in (("tenant-b", response.run_id), (who.tenant_id, "another-run")):
        with pytest.raises(LookupError):
            fresh.get(tenant, run, state.compiled_plan_reference)
    values = PolicyValueStore(stack.control.engine)
    ref = values.put("tenant-a", "run-1", {"k": "v"})
    assert PolicyValueStore(stack.control.engine).get("tenant-a", "run-1", ref) == {"k": "v"}
    with pytest.raises(LookupError):
        PolicyValueStore(stack.control.engine).get("tenant-b", "run-1", ref)
    values.discard("tenant-a", "run-1", ref)
    with pytest.raises(LookupError):
        PolicyValueStore(stack.control.engine).get("tenant-a", "run-1", ref)


def test_no_rows_are_stored_in_the_durable_tables(tmp_path):
    stack, _, _ = _run(tmp_path)
    with stack.control.engine.connect() as connection:
        dump = " ".join(
            str(row)
            for table in ("analytics_run_plans", "analytics_run_policy_values", "analytics_run_result_links")
            for row in connection.execute(text(f"SELECT * FROM {table}")).all()
        )
    assert "SELECT" in dump  # the plan is there
    for forbidden in ("1969", "1468", "563", "2024-03-01"):
        assert forbidden not in dump


def test_a_status_read_after_a_restart_never_runs_a_query_and_says_the_answer_is_unavailable(tmp_path):
    stack, who, response = _run(tmp_path)
    second = build_stack("duckdb", tmp_path)  # a new process on the same database
    reply = second.service().status(who, purpose=PURPOSE, run_id=response.run_id)
    assert reply.outcome.outcome == "failed" and reply.outcome.message == "The answer is unavailable."
    assert second.executed_sql == []


def test_resume_rebuilds_a_missing_result_only_for_a_stored_plan_and_only_through_the_executor(tmp_path):
    stack, who, response = _run(tmp_path)
    state = stack.control.load_latest_checkpoint(run_id=response.run_id, tenant_id=who.tenant_id, purpose=PURPOSE)
    second = build_stack("duckdb", tmp_path)
    second.nodes(
        who,
        __import__("app.runtime", fromlist=["BootstrapRequest"]).BootstrapRequest(
            request_id="x", request_text="Show monthly revenue", identity=who
        ),
    )
    with pytest.raises(LookupError):
        second.results.get(who.tenant_id, response.run_id, state.execution_reference)  # a plain read does not rebuild
    rebuilt = second.results.resume(who.tenant_id, response.run_id, state.execution_reference)
    assert [list(map(str, row)) for row in rebuilt.rows][0][1].startswith("1969")
    with pytest.raises(LookupError):
        second.results.resume("tenant-b", response.run_id, state.execution_reference)
    with pytest.raises(LookupError):
        second.results.resume(who.tenant_id, response.run_id, "0" * 64)


def test_a_store_without_an_engine_behaves_as_before(tmp_path):
    assert ExecutionResultStore().rebuilder is None
    with pytest.raises(LookupError):
        ExecutionResultStore().resume("t", "r", "x")
    with pytest.raises(LookupError):
        CompiledPlanStore().get("t", "r", "x")


def test_typed_parameters_round_trip_exactly(tmp_path):
    from datetime import date, datetime, timezone
    from decimal import Decimal

    from app.compiler.postgres import CompiledQuery

    stack, _, _ = _run(tmp_path)
    store = CompiledPlanStore(stack.control.engine)
    plan = CompiledQuery(
        sql="SELECT 1 WHERE a = :a",
        parameters={
            "a": Decimal("1.50"),
            "b": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "c": date(2024, 2, 1),
            "d": "x",
            "e": 3,
        },
    )
    reference = store.put("tenant-a", "run-typed", plan)
    again = CompiledPlanStore(stack.control.engine).get("tenant-a", "run-typed", reference)
    assert again.parameters == plan.parameters and type(again.parameters["a"]) is Decimal
    with pytest.raises(TypeError):
        CompiledPlanStore(stack.control.engine).put(
            "tenant-a", "run-bad", CompiledQuery(sql="s", parameters={"x": object()})
        )


def test_the_migration_adds_the_tables_and_downgrades_cleanly(tmp_path):
    from alembic import command
    from alembic.config import Config
    from reference_stack.stack import SERVICE_ROOT
    from sqlalchemy import create_engine, inspect

    database = f"sqlite:///{tmp_path / 'migrate.db'}"
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database)
    import os

    previous = os.environ.get("ANALYTICS_CONTROL_DB_URL")
    os.environ["ANALYTICS_CONTROL_DB_URL"] = database
    try:
        command.upgrade(config, "head")
        tables = set(inspect(create_engine(database)).get_table_names())
        assert {"analytics_run_plans", "analytics_run_policy_values", "analytics_run_result_links"} <= tables
        command.downgrade(config, "0011_rollouts")
        tables = set(inspect(create_engine(database)).get_table_names())
        assert not {"analytics_run_plans", "analytics_run_policy_values", "analytics_run_result_links"} & tables
    finally:
        if previous is None:
            os.environ.pop("ANALYTICS_CONTROL_DB_URL", None)
        else:
            os.environ["ANALYTICS_CONTROL_DB_URL"] = previous
