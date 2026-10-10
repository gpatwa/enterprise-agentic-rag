"""EA-060 to EA-065 deterministic evaluation and release gate tests."""
from app.evaluation import evaluate_case, fingerprint_rows, load_suite, release_gate
from packages.platform_contracts.analytics_intent import AnalyticalIntent, IntentMetric, SemanticContractReference
from packages.platform_contracts.evaluation import EvaluationCase


def intent():
    return AnalyticalIntent(
        query_id="q1", tenant_id="demo", dataset_id="orders",
        semantic_contract=SemanticContractReference(contract_id="sales", contract_version="v1"),
        metrics=[IntentMetric(metric_id="revenue")],
    )


def test_evaluation_grader_checks_typed_intent_and_outcome():
    case = EvaluationCase(case_id="c1", tenant_id="demo", question="revenue", expected_outcome="answer", expected_metric_ids=["revenue"], expected_dataset_id="orders")
    result = evaluate_case(case, outcome="answer", intent=intent())
    assert result.passed is True
    assert release_gate([result], "suite-1").blocked is False


def test_release_gate_blocks_regression():
    case = EvaluationCase(case_id="c1", tenant_id="demo", question="revenue", expected_outcome="answer", expected_metric_ids=["revenue"])
    result = evaluate_case(case, outcome="clarify", intent=intent())
    report = release_gate([result], "suite-1")
    assert report.blocked is True
    assert report.pass_rate == 0


def test_customer_suite_is_versioned_and_extensible_without_code_changes():
    suite = load_suite("tests/fixtures/evaluation/demo-suite-v1.json")
    assert suite.suite_version == "demo-suite-v1"
    assert {case.adversarial_type for case in suite.cases} == {"none", "ambiguity", "security"}
    assert fingerprint_rows([{"value": 1}, {"value": 2}]) == fingerprint_rows([{"value": 1}, {"value": 2}])
