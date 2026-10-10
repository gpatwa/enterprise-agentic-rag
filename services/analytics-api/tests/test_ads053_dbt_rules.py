"""ADS-053: dbt rules, the project reader, and the constraints the proposal contract enforces."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.proposals.dbt_project import DbtProject, canonical, find_column, has_test, render_edit
from app.proposals.dbt_rules import DbtFacts, DbtSpec, NoDbtProposal, decide_dbt
from packages.platform_contracts.proposals import ChangeProposal, DbtEdit

FIXTURE = Path(__file__).resolve().parent.parent / "reference_stack/dbt_fixture"
BASE = {
    "triage_category": "semantic",
    "triage_rule_id": "T-91",
    "basis_kind": "both",
    "model": "sales_orders",
    "correction_column": "amount",
    "correction_description": "Metric 'revenue' (sum).",
    "key_columns": ("id",),
    "measure_column": "amount",
}


def _facts(**overrides):
    return DbtFacts(**{**BASE, **overrides})


CASES = [
    ("disputed definition", _facts(), "add_column_description", "amount", "description", None, "D-20"),
    (
        "retrieval miss (T-90)",
        _facts(triage_category="retrieval", triage_rule_id="T-90"),
        "add_column_description",
        "amount",
        "description",
        None,
        "D-30",
    ),
    (
        "missing context (T-80)",
        _facts(triage_category="retrieval", triage_rule_id="T-80"),
        "add_column_description",
        "amount",
        "description",
        None,
        "D-30",
    ),
    (
        "fanout",
        _facts(
            triage_category="execution",
            triage_rule_id="T-40",
            basis_kind="system_evidence",
            issue_codes=("fanout_suspected",),
        ),
        "add_column_test",
        "id",
        "test",
        "unique",
        "D-10",
    ),
    (
        "duplicate group keys",
        _facts(
            triage_category="execution",
            triage_rule_id="T-40",
            basis_kind="system_evidence",
            issue_codes=("duplicate_group_keys",),
        ),
        "add_column_test",
        "id",
        "test",
        "unique",
        "D-10",
    ),
    (
        "null metric value",
        _facts(
            triage_category="execution",
            triage_rule_id="T-40",
            basis_kind="system_evidence",
            issue_codes=("invalid_metric_value",),
        ),
        "add_column_test",
        "amount",
        "test",
        "not_null",
        "D-15",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_each_rule_proposes_one_constrained_edit(case):
    _, facts, operation, column, edit, test_name, rule = case
    spec = decide_dbt(facts)
    assert isinstance(spec, DbtSpec)
    assert (spec.operation, spec.model, spec.column, spec.edit, spec.test_name, spec.rule_id) == (
        operation,
        "sales_orders",
        column,
        edit,
        test_name,
        rule,
    )
    assert decide_dbt(facts) == spec


EXEC = {"triage_category": "execution", "triage_rule_id": "T-40", "basis_kind": "system_evidence"}
NONE = [
    ("reporter claim only", _facts(basis_kind="reporter_claim"), "claim_only"),
    (
        "policy fault",
        _facts(triage_category="policy", triage_rule_id="T-10", basis_kind="system_evidence"),
        "category_not_applicable",
    ),
    ("undetermined", _facts(triage_category="undetermined", triage_rule_id="T-92"), "category_not_applicable"),
    ("no model", _facts(model=None), "no_model"),
    ("no target column", _facts(correction_column=None), "no_target"),
    (
        "composite key",
        _facts(**EXEC, issue_codes=("fanout_suspected",), key_columns=("a", "b")),
        "composite_key_unsupported",
    ),
    ("no key", _facts(**EXEC, issue_codes=("fanout_suspected",), key_columns=()), "composite_key_unsupported"),
    (
        "null metric without a measure",
        _facts(**EXEC, issue_codes=("invalid_metric_value",), measure_column=None),
        "no_target",
    ),
    (
        "execution fault with no table-level cause",
        _facts(**EXEC, issue_codes=("sort_violated",)),
        "no_matching_validation_code",
    ),
]


@pytest.mark.parametrize("case", NONE, ids=[c[0] for c in NONE])
def test_everything_else_yields_no_dbt_proposal_with_a_reason(case):
    _, facts, reason = case
    assert decide_dbt(facts) == NoDbtProposal(reason)


# ---- contract constraints ----


@pytest.mark.parametrize(
    "path",
    [
        "dbt_project.yml",
        "models/sales/sales_orders.sql",
        "../models/schema.yml",
        "models/../schema.yml",
        "macros/helpers.sql",
        "tests/assert_positive_amount.sql",
        "/etc/passwd",
        "models/sales/other.yml",
        "models/sales/schema.yaml",
        "models/sales/schema.yml.bak",
        "seeds/schema.yml",
        "models/sales/../../profiles.yml",
    ],
)
def test_a_dbt_edit_can_only_target_a_schema_file_under_models(path):
    with pytest.raises(ValidationError):
        DbtEdit(file_path=path, model="sales_orders", column="amount", edit="test", test_name="unique")
    DbtEdit(file_path="models/sales/schema.yml", model="sales_orders", column="amount", edit="test", test_name="unique")
    DbtEdit(file_path="models/schema.yml", model="sales_orders", column="amount", edit="test", test_name="unique")


def test_a_dbt_edit_is_one_description_or_one_standard_test_and_nothing_else():
    kwargs = {"file_path": "models/sales/schema.yml", "model": "sales_orders", "column": "amount"}
    for bad in (
        {"edit": "test", "test_name": "accepted_values"},
        {"edit": "test", "test_name": "relationships"},
        {"edit": "test"},
        {"edit": "test", "test_name": "unique", "description": "x"},
        {"edit": "description"},
        {"edit": "description", "description": "line one\nline two"},
        {"edit": "description", "description": "x", "test_name": "unique"},
    ):
        with pytest.raises(ValidationError):
            DbtEdit(**kwargs, **bad)
    for name in ("sales orders", "sales-orders", "x; drop", "1abc", ""):
        with pytest.raises(ValidationError):
            DbtEdit(**{**kwargs, "model": name}, edit="test", test_name="unique")


def _proposal(**overrides):
    edit = DbtEdit(
        file_path="models/sales/schema.yml", model="sales_orders", column="id", edit="test", test_name="unique"
    )
    fields = dict(
        proposal_id="p" * 8,
        tenant_id="t",
        kind="dbt",
        operation="add_column_test",
        target_kind="dbt_column",
        target_id="sales_orders.id",
        parameters={},
        base_contract="dbt:models/sales/schema.yml",
        base_contract_fingerprint="a" * 64,
        dbt_edit=edit,
        validation_commands=("dbt parse", "dbt test --select sales_orders"),
        rationale_codes=("rule:D-10",),
        origin_triage_id="tr",
        origin_feedback_id="fb",
        origin_run_id="run",
        rules_version="dbt-proposal-rules-v1",
        created_at=datetime.now(timezone.utc),
        content_fingerprint="b" * 64,
    )
    fields.update(overrides)
    return ChangeProposal(**fields)


def test_a_dbt_proposal_must_carry_safe_validation_commands_and_no_registry_patch():
    assert _proposal().status == "proposed"
    for bad in (
        (),
        ("dbt run",),
        ("dbt build",),
        ("dbt parse && rm -rf /",),
        ("dbt test",),
        ("dbt test --select a b",),
        ("dbt parse; echo hi",),
        ("dbt test --select $(whoami)",),
    ):
        with pytest.raises(ValidationError):
            _proposal(validation_commands=bad)
    with pytest.raises(ValidationError):
        _proposal(dbt_edit=None)
    with pytest.raises(ValidationError):
        _proposal(kind="semantic_context")  # only a dbt proposal carries a dbt edit


# ---- the project reader ----


def test_the_reader_sees_only_approved_schema_files_and_ignores_symlink_escapes(tmp_path):
    project = tmp_path / "p"
    shutil.copytree(FIXTURE, project)
    outside = tmp_path / "outside.yml"
    outside.write_text("models: [{name: leaked, columns: [{name: x}]}]\n")
    (project / "models/sales/link").mkdir()
    (project / "models/sales/link/schema.yml").symlink_to(outside)
    reader = DbtProject(project)
    assert reader.approved_files() == ["models/internal/schema.yml", "models/sales/schema.yml"]
    assert reader.locate_model("leaked") is None
    assert reader.locate_model("sales_orders").file_path == "models/sales/schema.yml"
    assert DbtProject(project, ("models/marts/**/schema.yml",)).locate_model("sales_orders") is None
    assert "dbt_project.yml" not in reader.approved_files() and not any(
        f.endswith(".sql") for f in reader.approved_files()
    )


def test_render_edit_changes_only_the_target_column_and_never_mutates_its_input():
    text = (FIXTURE / "models/sales/schema.yml").read_text()
    assert canonical(text) == text  # the fixture is stored in canonical form, so diffs are minimal
    described = render_edit(text, "sales_orders", "amount", description="D.", test_name=None)
    assert find_column(yaml.safe_load(described), "sales_orders", "amount")["description"] == "D."
    tested = render_edit(text, "sales_orders", "id", description=None, test_name="unique")
    column = find_column(yaml.safe_load(tested), "sales_orders", "id")
    assert column["data_tests"] == ["unique"] and column["description"] == "Order identifier."
    before, after = yaml.safe_load(text), yaml.safe_load(tested)
    after["models"][0]["columns"][0].pop("data_tests")
    assert before == after  # nothing else changed
    legacy = "models:\n- name: m\n  columns:\n  - name: c\n    tests:\n    - not_null\n"
    assert has_test(find_column(yaml.safe_load(legacy), "m", "c"), "not_null")
    assert "tests:" in render_edit(legacy, "m", "c", description=None, test_name="unique")  # keeps the project's key
    with pytest.raises(Exception, match="not found"):
        render_edit(text, "sales_orders", "nope", description="x", test_name=None)
