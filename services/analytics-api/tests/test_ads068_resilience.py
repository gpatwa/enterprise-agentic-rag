"""ADS-068: backup, verified restore, lease-takeover failover, rolling upgrade, and checkpoint compatibility."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from reference_stack import resilience_eval as drills
from reference_stack.stack import build_stack
from sqlalchemy import create_engine, text

from app.resilience import (
    EXCLUDED_TABLES,
    ResilienceError,
    backup_control_store,
    restore_control_store,
    verify_backup_files,
)
from app.resilience import backup as backup_module
from app.runtime import AgentGraphRunner, BootstrapRequest, ControlStore, governed_graph_v2
from app.runtime.analyze_service import GovernedAnalyzeService
from app.runtime.graph_runner import GraphRunError
from packages.platform_contracts.agent_runtime import AgentRunState
from packages.platform_contracts.resilience import ControlBackupManifest, ResilienceObjectives

SERVICE = Path(__file__).resolve().parent.parent
PURPOSE, QUESTION = "analytics", "Show monthly revenue"
OBJECTIVES = drills.load_objectives()


def _who(stack, user="requester"):
    return stack.verifier().verify(stack.token(user))


def _populated(tmp_path, name="a", **kwargs):
    stack = build_stack("duckdb", tmp_path / name, **kwargs)
    who = _who(stack)
    runs = [
        stack.service().analyze(who, purpose=PURPOSE, idempotency_key=f"bk-key-{i:05d}", request_text=QUESTION)
        for i in range(3)
    ]
    return stack, who, runs


# ---- objectives ----


def test_the_repository_objectives_are_valid_and_not_approved():
    assert OBJECTIVES.approval.status == "proposed" and OBJECTIVES.approval.approved_by is None
    assert OBJECTIVES.rpo_seconds == 900 and OBJECTIVES.rto_seconds == 900 and OBJECTIVES.lease_seconds == 30
    with pytest.raises(ValidationError, match="who approved"):
        ResilienceObjectives(
            objectives_version="v", rpo_seconds=1, rto_seconds=1, lease_seconds=1, approval={"status": "approved"}
        )
    with pytest.raises(ValidationError):
        ResilienceObjectives(
            objectives_version="v", rpo_seconds=0, rto_seconds=1, lease_seconds=1, approval={"status": "proposed"}
        )


# ---- backup and verified restore ----


def test_a_backup_captures_every_durable_table_but_not_leases_and_restores_identically(tmp_path):
    stack, who, runs = _populated(tmp_path)
    manifest = backup_control_store(stack.control.engine, tmp_path / "backup")
    assert not EXCLUDED_TABLES & set(manifest.tables) and "analytics_agent_runs" in manifest.tables
    assert (
        manifest.tables["analytics_agent_runs"].rows == 3 and manifest.tables["analytics_evidence_envelopes"].rows == 3
    )
    assert manifest.schema_revision == "0011_rollouts" and manifest.object_count > 100
    assert verify_backup_files(tmp_path / "backup") == manifest
    assert json.loads((tmp_path / "backup/manifest.json").read_text())["digest"] == manifest.digest
    target = build_stack("duckdb", tmp_path / "target")
    report = restore_control_store(tmp_path / "backup", target.control.engine)
    assert report["rows"] == manifest.object_count and report["evidence_envelopes"] == 3
    assert drills._run_states(target) == drills._run_states(stack)
    with target.control.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM analytics_run_leases")).scalar() == 0
    again = backup_control_store(target.control.engine, tmp_path / "second")
    assert again.tables == manifest.tables and again.digest == manifest.digest  # a restore is byte-for-byte faithful


def test_a_restored_database_is_a_working_one(tmp_path):
    stack, who, runs = _populated(tmp_path, review_threshold=1e-9)
    backup_control_store(stack.control.engine, tmp_path / "backup")
    target = build_stack("duckdb", tmp_path / "target", review_threshold=1e-9)
    restore_control_store(tmp_path / "backup", target.control.engine)
    status = target.service().status(who, purpose=PURPOSE, run_id=runs[0].run_id)
    assert status.state == "waiting_review" and status.outcome.outcome == "review"
    fresh = target.service().analyze(who, purpose=PURPOSE, idempotency_key="after-restore-1", request_text=QUESTION)
    assert fresh.state == "waiting_review"  # the restored database accepts new work
    assert target.evidence.verify_chain("tenant-a") == 0  # nothing was terminal yet, so there is no chain to extend


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        (lambda d: (d / "analytics_agent_runs.jsonl").write_text("{}\n"), "backup_corrupt"),
        (lambda d: (d / "analytics_agent_runs.jsonl").unlink(), "backup_table_missing"),
        (lambda d: (d / "manifest.json").write_text("{not json"), "backup_manifest_unreadable"),
        (
            lambda d: (d / "manifest.json").write_text(
                (d / "manifest.json")
                .read_text()
                .replace('"schema_revision": "0011_rollouts"', '"schema_revision": "0010_candidate_evaluations"')
            ),
            "backup_manifest_tampered",
        ),
        (
            lambda d: (d / "analytics_evidence_envelopes.jsonl").write_text(
                (d / "analytics_evidence_envelopes.jsonl").read_text().replace("succeeded", "failed")
            ),
            "backup_corrupt",
        ),
    ],
)
def test_a_damaged_backup_is_refused_before_anything_is_written(tmp_path, damage, code):
    stack, *_ = _populated(tmp_path)
    backup_control_store(stack.control.engine, tmp_path / "backup")
    damage(tmp_path / "backup")
    target = build_stack("duckdb", tmp_path / "target")
    with pytest.raises(ResilienceError) as caught:
        restore_control_store(tmp_path / "backup", target.control.engine)
    assert caught.value.code == code
    with target.control.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM analytics_agent_runs")).scalar() == 0


def test_restore_refuses_a_non_empty_target_a_different_schema_and_an_existing_backup_directory(tmp_path):
    stack, *_ = _populated(tmp_path)
    backup_control_store(stack.control.engine, tmp_path / "backup")
    with pytest.raises(ResilienceError) as occupied:
        restore_control_store(tmp_path / "backup", stack.control.engine)  # the source itself is not empty
    assert occupied.value.code == "target_not_empty"
    with pytest.raises(ResilienceError) as exists:
        backup_control_store(stack.control.engine, tmp_path / "backup")
    assert exists.value.code == "backup_destination_exists"
    database = f"sqlite:///{tmp_path / 'older.db'}"
    config = Config(str(SERVICE / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE / "alembic"))
    config.set_main_option("sqlalchemy.url", database)
    import os

    os.environ["ANALYTICS_CONTROL_DB_URL"] = database
    try:
        command.upgrade(config, "0010_candidate_evaluations")
    finally:
        os.environ.pop("ANALYTICS_CONTROL_DB_URL")
    with pytest.raises(ResilienceError) as mismatch:
        restore_control_store(tmp_path / "backup", create_engine(database))
    assert mismatch.value.code == "schema_revision_mismatch"


def test_a_failure_part_way_through_a_restore_leaves_the_target_empty(tmp_path, monkeypatch):
    stack, *_ = _populated(tmp_path)
    backup_control_store(stack.control.engine, tmp_path / "backup")
    target = build_stack("duckdb", tmp_path / "target")
    calls = {"n": 0}
    original = backup_module._decode_for_bind

    def failing(value):
        calls["n"] += 1
        if calls["n"] > 40:
            raise RuntimeError("disk full")
        return original(value)

    monkeypatch.setattr(backup_module, "_decode_for_bind", failing)
    with pytest.raises(RuntimeError):
        restore_control_store(tmp_path / "backup", target.control.engine)
    with target.control.engine.connect() as connection:
        assert (
            sum(
                connection.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
                for t in backup_module._tables(target.control.engine)
            )
            == 0
        )


def test_a_restore_that_breaks_the_evidence_chain_is_rejected(tmp_path):
    stack, *_ = _populated(tmp_path)
    manifest = backup_control_store(stack.control.engine, tmp_path / "backup")
    path = tmp_path / "backup/analytics_evidence_envelopes.jsonl"
    lines = path.read_text().splitlines()
    forged = json.loads(lines[1])
    forged["chain_hash"] = "f" * 64
    lines[1] = json.dumps(forged, sort_keys=True, separators=(",", ":"))
    path.write_text("".join(line + "\n" for line in lines))
    tables = dict(manifest.tables)
    tables["analytics_evidence_envelopes"] = type(tables["analytics_evidence_envelopes"])(
        rows=len(lines), digest=backup_module._digest(lines)
    )
    rewritten = ControlBackupManifest(
        backup_id=manifest.backup_id,
        created_at=manifest.created_at,
        schema_revision=manifest.schema_revision,
        tables=tables,
        digest=backup_module._overall(tables, manifest.schema_revision),
    )  # an operator who also re-signs the manifest still cannot forge the chain
    (tmp_path / "backup/manifest.json").write_text(rewritten.model_dump_json(indent=2))
    target = build_stack("duckdb", tmp_path / "target")
    with pytest.raises(ResilienceError) as caught:
        restore_control_store(tmp_path / "backup", target.control.engine)
    assert caught.value.code == "restored_evidence_chain_broken"


# ---- the drills against the objectives ----


def test_the_restore_drill_meets_the_objectives_and_reports_what_it_lost(tmp_path):
    drill = drills.drill_restore(tmp_path, OBJECTIVES, crash_after_seconds=600)
    result, measured = drill["result"], drill["measured"]
    assert result.drill == "restore" and result.passed and result.findings == []
    assert (
        measured["restore_seconds"] < OBJECTIVES.rto_seconds
        and measured["data_loss_window_seconds"] <= OBJECTIVES.rpo_seconds
    )
    assert measured["runs_in_backup"] == 5 and measured["runs_lost"] == 3  # exactly the writes after the backup
    assert measured["evidence_envelopes_verified"] == 2 and measured["feedback_restored"]
    assert measured["answer_rows_survive_restart"] is False  # documented: rows are process-local, evidence survives


def test_the_restore_drill_flags_a_missed_objective(tmp_path):
    late = drills.drill_restore(tmp_path / "late", OBJECTIVES, crash_after_seconds=1200)
    assert not late["result"].passed and late["result"].findings == ["rpo_exceeded"]
    strict = OBJECTIVES.model_copy(update={"rto_seconds": 1e-9})
    assert drills.drill_restore(tmp_path / "strict", strict)["result"].findings == ["rto_exceeded"]


def test_a_restored_service_answers_honestly_about_old_answers_and_never_executes_a_paused_run(tmp_path):
    stack, who, runs = _populated(tmp_path / "primary")
    paused = build_stack("duckdb", tmp_path / "primary2", review_threshold=1e-9)
    pending = paused.service().analyze(
        _who(paused), purpose=PURPOSE, idempotency_key="pause-key-0001", request_text=QUESTION
    )
    backup_control_store(paused.control.engine, tmp_path / "backup2")
    backup_control_store(stack.control.engine, tmp_path / "backup1")
    # 1. an answered run: the evidence is back, the rows are not, and the API says so instead of failing
    restored = build_stack("duckdb", tmp_path / "r1")
    restore_control_store(tmp_path / "backup1", restored.control.engine)
    old = restored.service().status(_who(restored), purpose=PURPOSE, run_id=runs[0].run_id)
    assert old.state == "terminal" and old.outcome.outcome == "failed" and old.outcome.error_code == "internal_error"
    assert "unavailable" in old.outcome.message
    # 2. a run paused for review: after a restart its compiled plan is gone, so the decision fails closed
    revived = build_stack("duckdb", tmp_path / "r2", review_threshold=1e-9)
    restore_control_store(tmp_path / "backup2", revived.control.engine)
    review = revived.control.get_review(pending.outcome.review_id, tenant_id="tenant-a", purpose=PURPOSE)
    decided = revived.service().decide_review(
        _who(revived, "reviewer"),
        purpose=PURPOSE,
        run_id=pending.run_id,
        decision="approved",
        plan_fingerprint=review.plan_fingerprint,
        note=None,
    )
    assert decided.state == "terminal" and decided.outcome.outcome != "answer"
    assert revived.executed_sql == []  # nothing executed on a plan that no longer exists


def test_the_failover_drill_takes_over_after_the_lease_runs_the_query_once_and_fences_the_zombie(tmp_path):
    drill = drills.drill_failover(tmp_path, OBJECTIVES)
    assert drill["result"].passed and drill["result"].findings == []
    measured = drill["measured"]
    assert measured["query_executions"] == 1 and measured["fencing_seq_after_takeover"] == 2
    assert measured["takeover_seconds"] <= OBJECTIVES.lease_seconds * OBJECTIVES.takeover_factor
    slow = OBJECTIVES.model_copy(update={"takeover_factor": 1.01})
    assert "takeover_too_slow" in drills.drill_failover(tmp_path / "slow", slow)["result"].findings


# ---- rolling upgrade and checkpoint compatibility ----


def test_the_pinned_checkpoint_fixtures_are_unchanged_and_still_load_and_round_trip(tmp_path):
    lock = json.loads(drills.FIXTURE_LOCK.read_text())
    assert set(lock["sha256"]) == {"waiting_review", "waiting_clarification", "terminal_succeeded", "terminal_refused"}
    stack = build_stack("duckdb", tmp_path / "fx")
    for name, digest in lock["sha256"].items():
        raw = (drills.FIXTURES / f"{name}.json").read_text()
        assert hashlib.sha256(raw.encode()).hexdigest() == digest, (
            f"{name}: regenerate only with a compatibility decision"
        )
        state = AgentRunState.model_validate_json(raw)
        assert (
            json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n" == raw
        )  # serialization is stable
        stack.control.create_run(state)
        assert (
            stack.control.load_run_state(run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose) == state
        )
    states = {n: AgentRunState.model_validate_json((drills.FIXTURES / f"{n}.json").read_text()) for n in lock["sha256"]}
    assert states["waiting_review"].status == "waiting_approval" and states["waiting_clarification"].clarification_state
    assert (
        states["terminal_succeeded"].terminal_outcome.kind == "succeeded"
        and states["terminal_refused"].terminal_outcome.kind == "refused"
    )


def test_the_upgrade_rule_new_fields_must_be_optional_and_unknown_ones_are_refused_not_misread():
    payload = json.loads((drills.FIXTURES / "terminal_succeeded.json").read_text())
    older = {
        k: v
        for k, v in payload.items()
        if k
        in {  # what an older writer produced: only the long-standing required fields
            "run_id",
            "request_id",
            "tenant_id",
            "purpose",
            "graph_version",
            "current_node",
            "status",
            "transition_count",
            "context_snapshot_id",
            "budget",
            "terminal_outcome",
            "schema_version",
        }
    }
    assert (
        AgentRunState.model_validate(older).run_id == payload["run_id"]
    )  # optional fields default: a newer reader accepts it
    with pytest.raises(ValidationError):
        AgentRunState.model_validate({**payload, "a_future_field": 1})  # an older reader refuses a newer writer's state
    with pytest.raises(ValidationError):
        AgentRunState.model_validate({**payload, "schema_version": "v2"})


def test_a_database_upgraded_with_data_in_it_keeps_the_data_and_survives_a_downgrade(tmp_path):
    import os

    database = f"sqlite:///{tmp_path / 'upgrade.db'}"
    config = Config(str(SERVICE / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE / "alembic"))
    config.set_main_option("sqlalchemy.url", database)
    os.environ["ANALYTICS_CONTROL_DB_URL"] = database
    try:
        command.upgrade(config, "0002_agent_control_store")
        state = AgentRunState.model_validate_json((drills.FIXTURES / "waiting_review.json").read_text())
        engine = create_engine(database)
        ControlStore(engine).create_run(state)
        command.upgrade(config, "head")
        assert (
            ControlStore(engine).load_run_state(run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose)
            == state
        )
        command.downgrade(config, "0010_candidate_evaluations")
        command.upgrade(config, "head")
        assert (
            ControlStore(engine).load_run_state(run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose)
            == state
        )
    finally:
        os.environ.pop("ANALYTICS_CONTROL_DB_URL")


def test_a_run_started_by_one_worker_is_finished_by_a_differently_built_worker_and_unknown_graphs_are_refused(tmp_path):
    stack = build_stack("duckdb", tmp_path / "mixed", review_threshold=1e-9)
    who, reviewer = _who(stack), _who(stack, "reviewer")
    paused = stack.service().analyze(who, purpose=PURPOSE, idempotency_key="mixed-key-0001", request_text=QUESTION)
    review = stack.control.get_review(paused.outcome.review_id, tenant_id="tenant-a", purpose=PURPOSE)
    seen: list[str] = []

    def upgraded_runner(identity, request):
        nodes = stack.nodes(identity, request)
        wrapped = {}
        for node_id, handler in nodes.items():

            def run(ni, _h=handler, _n=node_id):
                seen.append(_n)  # the "new build" observes every node it runs
                return _h(ni)

            wrapped[node_id] = run
        return AgentGraphRunner(stack.control, governed_graph_v2(wrapped))

    stack.runner = upgraded_runner
    service = GovernedAnalyzeService(
        stack.control, runner_factory=upgraded_runner, state_factory=stack.new_state, answers=stack, sealer=None
    )
    done = service.decide_review(
        reviewer,
        purpose=PURPOSE,
        run_id=paused.run_id,
        decision="approved",
        plan_fingerprint=review.plan_fingerprint,
        note=None,
    )
    assert done.state == "terminal" and done.outcome.outcome == "answer" and "execute" in seen and "create" not in seen
    request = BootstrapRequest(request_id="x-request-1", request_text=QUESTION, identity=who)
    runner = AgentGraphRunner(stack.control, governed_graph_v2(stack.nodes(who, request)))
    foreign = stack.new_state(request, "foreign-run-0001", PURPOSE).model_copy(update={"graph_version": "graph-v9"})
    with pytest.raises(GraphRunError):
        runner.start(
            foreign, owner_id="w", lease_token="t"
        )  # a graph this build does not know is refused, not guessed at
    assert len(stack.executed_sql) == 1  # only the earlier, approved run ever executed a query


def test_nothing_mounts_the_resilience_tooling_yet():
    for path in (SERVICE / "app/main.py", SERVICE / "app/api_v2.py"):
        assert "app.resilience" not in path.read_text(), path.name
