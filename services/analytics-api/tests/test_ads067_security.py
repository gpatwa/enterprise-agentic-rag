"""ADS-067: threat model, prompt-injection, exfiltration, and inference suite; findings register."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from reference_stack import security_eval
from reference_stack.stack import build_stack
from test_ads040_execution_gateways import _contract, _intent
from test_ads041_result_validation import _intent_wide, _plan, _result

from app.compiler import DuckDBCompilerAdapter, PostgreSQLCompilerAdapter
from app.compiler.postgres import CompilationError, PostgreSQLCompiler
from app.execution import DuckDBGateway, ExecutionLimits, PostgresGateway, validate_result
from app.runtime.analyze_service import GovernedAnalyzeService, ServiceError
from packages.platform_contracts.semantic import SemanticDimension

SERVICE = Path(__file__).resolve().parent.parent
THREAT_MODEL = SERVICE.parent.parent / "docs/execution/enterprise-analytics/security/threat-model.md"


@pytest.fixture(scope="module")
def report(security_report):
    return security_report


def _cases(report, *ids):
    by_id = {c["case_id"]: c for c in report["cases"]}
    return [by_id[i] for i in ids]


# ---- the corpus and its findings register ----


def test_the_security_corpus_meets_its_proposed_thresholds_and_stays_unapproved(report):
    failed = [(c["case_id"], c["detail"]) for c in report["cases"] if not c["passed"]]
    assert not failed, failed
    unmet = {name: gate for name, gate in report["gates"].items() if not gate["meets"]}
    assert report["meets_thresholds"] and not unmet and len(report["cases"]) == 31, unmet
    assert report["approval"]["status"] == "proposed" and report["approval"]["approved_by"] is None
    markdown = security_eval.render_markdown(report)
    assert "PROPOSED and NOT APPROVED" in markdown and "not an independent security review" in markdown
    assert "Findings register" in markdown and "open_decision" in markdown


def test_the_hostile_model_and_injection_cases_run_nothing(report):
    cases = _cases(report, "PI01", "PI03", "PI04", "PI05", "PI06", "PI07", "PI08", "IN01", "IN02")
    assert all(c["got"] == "no_execution" and c["passed"] for c in cases)
    assert report["gates"]["hostile_statements_executed"]["value"] == 0
    assert _cases(report, "PI02")[0]["got"] == "plan_is_benign"
    assert _cases(report, "PI09")[0]["got"] == "parameterized"  # the payload is a bound value, never SQL text


def test_the_hostile_explainer_cases_degrade_to_evidence_only(report):
    assert [c["got"] for c in _cases(report, "PI11", "PI12")] == ["evidence_only", "evidence_only"]


def test_request_text_cannot_break_out_of_the_prompts_data_block(report):
    assert _cases(report, "PI10")[0]["got"] == "escaped"


def test_another_tenants_reads_return_not_found(report):
    assert [c["got"] for c in _cases(report, "EX01", "EX02")] == ["run_not_found", "run_not_found"]
    assert [c["got"] for c in _cases(report, "EX04", "EX05", "EX06")] == ["401", "401", "403"]
    assert _cases(report, "EX03")[0]["got"] == "clean"


def test_every_finding_cites_evidence_and_no_critical_or_high_finding_is_unresolved_at_pilot_scope(report):
    findings = {f["id"]: f for f in report["findings"]}
    assert set(findings) == {"F-01", "F-02", "F-03", "F-04", "F-05", "F-06"}
    assert report["gates"]["findings_without_evidence"]["value"] == 0
    assert report["unresolved"] == [] and findings["F-03"]["status"] == "open_decision"
    assert findings["F-03"]["severity"] == "high" and findings["F-03"]["pilot_scope_severity"] == "medium"
    assert all(
        f["status"] in {"resolved", "mitigated", "accepted_by_design", "open_decision"} for f in findings.values()
    )
    assert all(
        f.get("residual")
        for f in findings.values()
        if f["status"] in {"mitigated", "open_decision", "accepted_by_design"}
    )
    gap_findings = {
        c["finding"] for c in json.loads(security_eval.CORPUS.read_text())["cases"] if c["kind"] == "known_gap"
    }
    assert gap_findings <= set(findings)


def test_the_documented_gaps_stay_true(report):
    assert [c["got"] for c in _cases(report, "GAP01", "GAP02", "GAP03")] == [
        "readable",
        "row_level_value_returned",
        "differencing_possible",
    ]


def test_the_evaluation_fails_when_a_control_is_weakened(tmp_path, monkeypatch):
    """The corpus must be able to fail: ignore the minimum cohort and the inference controls stop working."""
    original = PostgreSQLCompiler.__init__
    monkeypatch.setattr(
        PostgreSQLCompiler, "__init__", lambda self, *, min_cohort=None: original(self, min_cohort=None)
    )
    weakened = security_eval.run_corpus(tmp_path)
    failed = {c["case_id"] for c in weakened["cases"] if not c["passed"]}
    assert {"IN02", "IN03", "IN04"} <= failed
    assert not weakened["meets_thresholds"] and not weakened["gates"]["control_agreement"]["meets"]


def test_a_wrong_expectation_or_a_changed_corpus_is_detected(tmp_path, monkeypatch):
    suite, thresholds = security_eval.load_suite()
    bad = json.loads(json.dumps(suite))
    next(c for c in bad["cases"] if c["id"] == "EX01")["expect"] = "readable"
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(bad))
    forged = tmp_path / "thresholds.json"
    forged.write_text(json.dumps({**thresholds, "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest()}))
    monkeypatch.setattr(security_eval, "CORPUS", corpus)
    monkeypatch.setattr(security_eval, "THRESHOLDS", forged)
    changed = security_eval.run_corpus(tmp_path / "run")
    assert not changed["meets_thresholds"] and not changed["gates"]["control_agreement"]["meets"]
    forged.write_text(json.dumps(thresholds))
    with pytest.raises(security_eval.SecuritySuiteLockError):
        security_eval.load_suite()


# ---- the threat model cannot go stale ----


def test_every_verification_reference_in_the_threat_model_exists():
    text = THREAT_MODEL.read_text()
    references = re.findall(r"`(tests/[\w./]+\.py)::(test_\w+)`", text)
    assert len(references) >= 30
    for path, name in references:
        source = (SERVICE / path).read_text()
        assert re.search(rf"^def {name}\(", source, re.M), (path, name)
    threat_ids = re.findall(r"^\| (T-\d+) \|", text, re.M)
    assert threat_ids == [f"T-{n:02d}" for n in range(1, len(threat_ids) + 1)] and len(threat_ids) >= 20
    for row in re.findall(r"^\| T-\d+ \|.*$", text, re.M):
        assert "tests/" in row and row.count("|") == 7  # every threat names its verification and its residual risk
    assert "not** an independent security review" in text


# ---- the hardening behind the findings ----


def test_the_compiler_refuses_row_level_groupings():
    contract, intent = (
        _contract(),
        _intent(group_by=[{"dimension_id": "created_at"}], sort=[], filters=[], time_range=None),
    )
    for adapter in (DuckDBCompilerAdapter(), PostgreSQLCompilerAdapter()):
        with pytest.raises(CompilationError, match="time granularity"):
            adapter.compile(intent, contract)
        bucketed = _intent(
            group_by=[{"dimension_id": "created_at", "time_granularity": "day"}], sort=[], filters=[], time_range=None
        )
        assert "DATE_TRUNC('day'" in adapter.compile(bucketed, contract).sql
    keyed = contract.model_copy(
        update={
            "dimensions": [
                *contract.dimensions,
                SemanticDimension(
                    id="order_id",
                    dataset_id="orders",
                    field_id="orders.id",
                    dimension_type="identifier",
                    owner_ids=["team.data"],
                ),
            ]
        }
    )
    by_key = _intent(group_by=[{"dimension_id": "order_id"}], sort=[], filters=[], time_range=None)
    with pytest.raises(
        ValueError, match="order_id"
    ):  # the certified contract has no such dimension: refused earlier still
        DuckDBCompilerAdapter().compile(by_key, contract)
    with pytest.raises(CompilationError, match="grain key"):
        DuckDBCompilerAdapter().compile(by_key, keyed)


def test_the_minimum_cohort_is_validated_and_suppression_is_a_warning_not_a_failure():
    for bad in (1, 0, -3, 10_001):
        with pytest.raises(ValueError, match="min_cohort"):
            DuckDBCompilerAdapter(min_cohort=bad)
    contract = _contract()
    intent = _intent_wide()
    plain = DuckDBCompilerAdapter().compile(intent, contract)
    guarded = DuckDBCompilerAdapter(min_cohort=5).compile(intent, contract)
    assert "HAVING" not in plain.sql and "HAVING COUNT(*) >= 5" in guarded.sql
    assert guarded.sql.index("GROUP BY") < guarded.sql.index("HAVING") < guarded.sql.index("ORDER BY")
    totals = {"revenue": Decimal("10")}
    cols = ["dimension_0", "metric_0"]
    short = _result(cols, [("a", 6), ("b", 3)])  # 9 of 10: one small group withheld
    assert validate_result(short, _plan(), intent, contract, control_totals=totals).blocking_codes == (
        "missing_groups_suspected",
    )
    suppressed = validate_result(short, _plan(), intent, contract, control_totals=totals, min_cohort=5)
    assert suppressed.status == "valid_with_warnings" and [i.code for i in suppressed.issues] == ["groups_suppressed"]
    surplus = _result(cols, [("a", 8), ("b", 7)])  # 15 of 10 is a fanout whatever the suppression
    assert validate_result(surplus, _plan(), intent, contract, control_totals=totals, min_cohort=5).blocking_codes == (
        "fanout_suspected",
    )
    nothing = validate_result(_result(cols, []), _plan(), intent, contract, control_totals=totals, min_cohort=5)
    assert nothing.blocking_codes == ("cohort_too_small",)


def test_an_empty_result_with_an_empty_total_is_valid():
    contract, intent = _contract(), _intent_wide()
    empty = _result(["dimension_0", "metric_0"], [])
    assert validate_result(empty, _plan(), intent, contract, control_totals={"revenue": None}).status == "valid"
    assert validate_result(
        empty, _plan(), intent, contract, control_totals={"revenue": Decimal("5")}
    ).blocking_codes == ("missing_groups_suspected",)  # an empty result against a non-empty total is still a failure


def test_a_server_key_makes_run_ids_underivable(tmp_path):
    keyed = build_stack("duckdb", tmp_path / "keyed", run_id_key=b"k" * 32)
    plain = build_stack("duckdb", tmp_path / "plain")
    who = keyed.verifier().verify(keyed.token("requester"))
    derivable = GovernedAnalyzeService.derive_run_id(who, "analytics", "guessable-key-1")
    assert plain.service().run_id_for(who, "analytics", "guessable-key-1") == derivable
    keyed_id = keyed.service().run_id_for(who, "analytics", "guessable-key-1")
    assert keyed_id != derivable and len(keyed_id) == 32
    assert keyed.service().run_id_for(who, "analytics", "guessable-key-1") == keyed_id  # still idempotent
    other = build_stack("duckdb", tmp_path / "other", run_id_key=b"j" * 32)
    assert other.service().run_id_for(who, "analytics", "guessable-key-1") not in {keyed_id, derivable}
    keyed.service().analyze(
        who, purpose="analytics", idempotency_key="guessable-key-1", request_text="Show monthly revenue"
    )
    colleague = keyed.verifier().verify(keyed.token("colleague"))
    with pytest.raises(ServiceError) as caught:
        keyed.service().status(colleague, purpose="analytics", run_id=derivable)
    assert caught.value.code == "run_not_found"


def test_the_session_time_zone_is_pinned_to_utc(tmp_path):
    stack = build_stack("duckdb", tmp_path / "tz")
    connection = stack.gateway._connect()
    try:
        assert connection.execute("SELECT current_setting('TimeZone')").fetchone()[0] == "UTC"
    finally:
        connection.close()
    assert isinstance(stack.gateway, DuckDBGateway) and ExecutionLimits().timeout_seconds > 0
    statements = []

    class Recorder:
        def __init__(self):
            self.rolled = 0

        def exec_driver_sql(self, statement):
            statements.append(statement)

    PostgresGateway._begin_read_only(Recorder(), timeout_seconds=1.0)
    assert "SET LOCAL TIME ZONE 'UTC'" in statements and statements[0] == "SET TRANSACTION READ ONLY"


def test_the_data_plane_agent_accepts_a_minimum_cohort():
    import inspect

    from app.data_plane import DataPlaneAgent

    assert "min_cohort" in inspect.signature(DataPlaneAgent.__init__).parameters


def test_nothing_mounts_the_security_evaluation_yet():
    for path in (SERVICE / "app/main.py", SERVICE / "app/api_v2.py"):
        assert "security_eval" not in path.read_text(), path.name
