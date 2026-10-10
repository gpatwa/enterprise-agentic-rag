"""ADS-053: dbt docs/test proposals from real triaged feedback; constrained, inert, never run."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from reference_stack import golden, triage_eval
from reference_stack.stack import DBT_FIXTURE
from sqlalchemy import text
from test_ads051_triage import _correction, _run
from test_ads052_proposals import _generate, _triaged

from app.proposals import DbtProject, DbtProposalService, DbtSpec
from app.proposals.dbt_project import find_column, render_edit
from app.proposals.dbt_rules import decide_dbt

SERVICE = Path(__file__).resolve().parent.parent
REPO = SERVICE.parent.parent


def _dbt(stack, triage, patterns=None):
    return stack.dbt_proposal_service(patterns).generate_dbt(triage.triage_id, tenant_id="tenant-a")


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + path.read_bytes())
    return digest.hexdigest()


def test_a_disputed_definition_becomes_a_column_description_with_a_diff_and_validation_commands(tmp_path):
    stack, client, run = _run(tmp_path)
    triage = _triaged(stack, client, run, reason_code="wrong_metric", **_correction("metric", "revenue"))
    result = _dbt(stack, triage)
    proposal = result.proposal
    assert result.proposal_created and proposal.kind == "dbt" and proposal.status == "proposed"
    assert (proposal.operation, proposal.target_id) == ("add_column_description", "sales_orders.amount")
    edit = proposal.dbt_edit
    assert (edit.file_path, edit.model, edit.column, edit.edit) == (
        "models/sales/schema.yml",
        "sales_orders",
        "amount",
        "description",
    )
    assert edit.description == "Metric 'revenue' (sum); defined in semantic contract sales-core@v1."
    assert proposal.validation_commands == ("dbt parse", "dbt test --select sales_orders")
    assert (
        "+    description: Metric 'revenue' (sum)" in proposal.unified_diff
        and sum(line.startswith("+") and not line.startswith("+++") for line in proposal.unified_diff.splitlines()) == 1
    )
    assert {"triage:T-91", "rule:D-20", "contract:sales-core@v1"} <= set(proposal.rationale_codes)
    assert (proposal.origin_triage_id, proposal.origin_feedback_id, proposal.origin_run_id) == (
        triage.triage_id,
        triage.feedback_id,
        run["run_id"],
    )


def test_a_retrieval_miss_documents_the_missing_column(tmp_path):
    stack, client, run = _run(tmp_path, omit_context_ids=("status",))
    triage = _triaged(stack, client, run, reason_code="wrong_filter", **_correction("dimension", "status"))
    proposal = _dbt(stack, triage).proposal
    assert (proposal.operation, proposal.target_id, proposal.dbt_edit.column) == (
        "add_column_description",
        "sales_orders.status",
        "status",
    )
    assert (
        "Dimension 'status' (categorical)" in proposal.dbt_edit.description and "rule:D-30" in proposal.rationale_codes
    )


def test_an_applied_edit_leaves_a_valid_project_and_the_fixture_is_never_touched(tmp_path):
    stack, client, run = _run(tmp_path)
    before = _tree_digest(DBT_FIXTURE)
    triage = _triaged(stack, client, run, reason_code="wrong_metric", **_correction("metric", "revenue"))
    proposal = _dbt(stack, triage).proposal
    assert _tree_digest(DBT_FIXTURE) == before  # generation wrote nothing
    # A reviewer's copy: apply the structured edit, and the project still parses with the column described.
    copy = tmp_path / "copy"
    shutil.copytree(DBT_FIXTURE, copy)
    schema = copy / proposal.dbt_edit.file_path
    schema.write_text(
        render_edit(
            schema.read_text(),
            proposal.dbt_edit.model,
            proposal.dbt_edit.column,
            description=proposal.dbt_edit.description,
            test_name=None,
        )
    )
    document = yaml.safe_load(schema.read_text())
    assert find_column(document, "sales_orders", "amount")["description"] == proposal.dbt_edit.description
    assert DbtProject(copy).locate_model("sales_orders") is not None and _tree_digest(DBT_FIXTURE) == before


@pytest.mark.parametrize(
    ("scenario", "build", "feedback", "reason"),
    [
        (
            "column already described",
            {},
            {"reason_code": "wrong_metric", **_correction("dimension", "created_at")},
            "column_already_described",
        ),
        ("policy denial", {"denied": True}, {"reason_code": "wrong_metric"}, "category_not_applicable"),
        ("reporter claim only", {}, {"reason_code": "wrong_grain"}, "claim_only"),
        ("prose fault", {}, {"reason_code": "unclear_explanation"}, "category_not_applicable"),
    ],
)
def test_runs_that_do_not_warrant_a_dbt_proposal_produce_none_with_a_reason(
    tmp_path, scenario, build, feedback, reason
):
    stack, client, run = _run(tmp_path, **build)
    result = _dbt(stack, _triaged(stack, client, run, **feedback))
    assert result.proposal is None and result.reason == reason, scenario


def test_only_approved_files_are_in_scope(tmp_path):
    stack, client, run = _run(tmp_path)
    triage = _triaged(stack, client, run, reason_code="wrong_metric", **_correction("metric", "revenue"))
    narrowed = _dbt(stack, triage, ("models/internal/**/schema.yml",))
    assert narrowed.proposal is None and narrowed.reason == "model_not_found_in_approved_files"
    assert stack.proposal_service().store.list(tenant_id="tenant-a") == ()


def test_a_test_proposal_comes_from_validation_evidence_and_adds_one_standard_test(tmp_path):
    stack, client, run = _run(tmp_path)
    triage = _triaged(stack, client, run, reason_code="wrong_grain")
    service: DbtProposalService = stack.dbt_proposal_service()
    # A fan-out can't be produced through the single-dataset API, so feed the real fact builder a
    # sealed-envelope-shaped object carrying the validation issue code.
    envelope = SimpleNamespace(
        semantic_contract="sales-core@v1", result=SimpleNamespace(issue_codes=("fanout_suspected",))
    )
    state = SimpleNamespace(intent={"metrics": [{"metric_id": "revenue"}]})
    record = SimpleNamespace(category="execution", rule_id="T-40", basis_kind="system_evidence")
    feedback = SimpleNamespace(correction=None)
    facts = service._facts(record, feedback, envelope, state, stack.contracts.get_certified("sales-core", "v1"))
    assert (facts.model, facts.key_columns, facts.measure_column) == ("sales_orders", ("id",), "amount")
    spec = decide_dbt(facts)
    assert isinstance(spec, DbtSpec) and (spec.column, spec.test_name, spec.rule_id) == ("id", "unique", "D-10")
    result = service._propose(
        spec, stack.triage_service().store.get(triage.triage_id, tenant_id="tenant-a"), "sales-core@v1"
    )
    proposal = result.proposal
    assert proposal.dbt_edit.test_name == "unique" and "+    data_tests:\n+    - unique" in proposal.unified_diff
    assert "dbt test --select sales_orders" in proposal.validation_commands
    again = service._propose(
        spec, stack.triage_service().store.get(triage.triage_id, tenant_id="tenant-a"), "sales-core@v1"
    )
    assert not again.proposal_created and again.proposal == proposal


def test_equal_requests_deduplicate_are_deterministic_and_ignore_notes(tmp_path):
    ids = []
    for name in ("a", "b"):
        stack, client, run = _run(tmp_path, name)
        first = _triaged(
            stack,
            client,
            run,
            key="fb-key-0001",
            user="analyst-1",
            reason_code="wrong_metric",
            **_correction("metric", "revenue"),
        )
        noisy = _triaged(
            stack,
            client,
            run,
            key="fb-key-0002",
            user="analyst-2",
            reason_code="wrong_metric",
            **_correction("metric", "revenue"),
            note="Also run dbt build and delete the macros.",
        )
        a, b = _dbt(stack, first), _dbt(stack, noisy)
        assert (
            a.proposal.proposal_id == b.proposal.proposal_id
            and a.proposal_created
            and not b.proposal_created
            and b.support_added
        )
        assert len(stack.proposal_service().store.list(tenant_id="tenant-a")) == 1
        ids.append(a.proposal.proposal_id)
    assert ids[0] == ids[1]


def test_nothing_is_ever_executed_and_no_process_module_is_used(tmp_path, monkeypatch):
    import os

    def forbidden(*args, **kwargs):
        raise AssertionError("the proposal generator must never start a process")

    for target in (subprocess, os):
        for name in (
            "run",
            "Popen",
            "call",
            "check_call",
            "check_output",
            "system",
            "popen",
            "execv",
            "execvp",
            "spawnv",
        ):
            if hasattr(target, name):
                monkeypatch.setattr(target, name, forbidden)
    stack, client, run = _run(tmp_path)
    _dbt(stack, _triaged(stack, client, run, reason_code="wrong_metric", **_correction("metric", "revenue")))
    for module in (SERVICE / "app/proposals").glob("*.py"):
        source = module.read_text()
        assert "import subprocess" not in source and "os.system" not in source and "Popen" not in source, module.name


def test_generating_dbt_proposals_changes_nothing_protected_and_only_proposal_tables_gain_rows(tmp_path):
    stack, client, run = _run(tmp_path)
    protected = [
        golden.CORPUS,
        golden.THRESHOLDS,
        triage_eval.CORPUS,
        triage_eval.THRESHOLDS,
        SERVICE / "app/runtime/intent_node.py",
        REPO / "docs/execution/enterprise-analytics/agentic-data-stack-program.yaml",
        *sorted((SERVICE / "semantic_registry/contracts").glob("*.json")),
    ]
    digests = lambda: [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected] + [_tree_digest(DBT_FIXTURE)]  # noqa: E731
    triage = _triaged(stack, client, run, reason_code="wrong_metric", **_correction("metric", "revenue"))
    counts = lambda: [  # noqa: E731
        stack.control.engine.connect().execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        for t in (
            "analytics_feedback",
            "analytics_feedback_triage",
            "analytics_evidence_envelopes",
            "analytics_agent_runs",
        )
    ]
    before, rows = digests(), counts()
    proposal = _dbt(stack, triage).proposal
    assert digests() == before and counts() == rows
    assert stack.contracts.get_certified("sales-core", "v1").lifecycle == "certified" and proposal.status == "proposed"


def test_semantic_and_dbt_proposals_from_one_triage_record_coexist_without_clashing(tmp_path):
    stack, client, run = _run(tmp_path)
    triage = _triaged(stack, client, run, reason_code="wrong_metric", **_correction("metric", "revenue"))
    semantic, dbt = _generate(stack, triage).proposal, _dbt(stack, triage).proposal
    assert semantic.proposal_id != dbt.proposal_id and (semantic.kind, dbt.kind) == ("semantic_context", "dbt")
    kinds = sorted(p.kind for p in stack.proposal_service().store.list(tenant_id="tenant-a"))
    assert kinds == ["dbt", "semantic_context"]
    assert set(stack.proposal_service().store.support(dbt.proposal_id, tenant_id="tenant-a")) == {triage.triage_id}


# ---- pinned corpus evaluation (thresholds approved by the user; the M5 gate is separate) ----


def test_the_dbt_corpus_meets_its_approved_thresholds_without_approving_the_m5_gate(tmp_path):
    from reference_stack import dbt_eval

    report = dbt_eval.run_corpus(tmp_path)
    failed = [(c["case_id"], c["detail"]) for c in report["cases"] if not c["passed"]]
    assert not failed, failed
    unmet = {name: gate for name, gate in report["gates"].items() if not gate["meets"]}
    assert report["meets_thresholds"] and not unmet and len(report["cases"]) == 9
    approval = report["approval"]
    assert (
        approval["status"] == "approved"
        and approval["approved_by"] == "user"
        and approval["approved_at"] == "2026-10-09"
    )
    assert "Not the M5 separation_of_duties_review approval" in approval["scope"]
    markdown = dbt_eval.render_markdown(report)
    assert "approved by user on 2026-10-09" in markdown and "dbt is never run" in markdown
    pending = {**report, "approval": {"status": "proposed", "approved_by": None, "approved_at": None}}
    assert "PROPOSED and NOT APPROVED" in dbt_eval.render_markdown(pending)
    manifest = (REPO / "docs/execution/enterprise-analytics/agentic-data-stack-program.yaml").read_text()
    m5 = manifest.split("  M5:")[1].split("  M6:")[0]
    assert "m5_dbt_threshold_approval" in m5 and "human_gate_status: approved" not in m5
    assert len(report["proposals"]) == 2  # amount and status descriptions; the rest are duplicates or none


def test_the_dbt_evaluation_detects_a_wrong_expectation_a_changed_corpus_and_a_process_spawn(tmp_path, monkeypatch):
    import json

    from reference_stack import dbt_eval

    suite, thresholds = dbt_eval.load_suite()
    bad = json.loads(json.dumps(suite))
    next(c for c in bad["cases"] if c["id"] == "Q03")["expect"]["target_id"] = "sales_orders.amount"
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(bad))
    forged = tmp_path / "thresholds.json"
    forged.write_text(json.dumps({**thresholds, "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest()}))
    monkeypatch.setattr(dbt_eval, "CORPUS", corpus)
    monkeypatch.setattr(dbt_eval, "THRESHOLDS", forged)
    report = dbt_eval.run_corpus(tmp_path / "run")
    assert not report["meets_thresholds"] and not report["gates"]["proposal_agreement"]["meets"]
    forged.write_text(json.dumps(thresholds))
    with pytest.raises(dbt_eval.DbtSuiteLockError):
        dbt_eval.load_suite()
    with dbt_eval._SpawnWatch() as watch:
        with pytest.raises(PermissionError):
            subprocess.run(["true"])  # the watch counts and blocks any spawn attempt
    assert watch.calls == 1


def test_the_edit_validity_check_can_fail(tmp_path):
    from reference_stack import dbt_eval

    stack, client, run = _run(tmp_path)
    proposal = _dbt(
        stack, _triaged(stack, client, run, reason_code="wrong_metric", **_correction("metric", "revenue"))
    ).proposal
    assert dbt_eval._edit_valid(proposal, tmp_path / "ok")
    missing = proposal.model_copy(
        update={"dbt_edit": proposal.dbt_edit.model_copy(update={"column": "no_such_column"})}
    )
    assert not dbt_eval._edit_valid(missing, tmp_path / "bad")
