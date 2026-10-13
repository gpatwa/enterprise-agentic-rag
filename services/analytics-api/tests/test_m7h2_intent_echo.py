"""M7-H2: the question and the interpreted intent must agree, using only certified terms; nothing is guessed."""

from __future__ import annotations

import json

import pytest
from reference_stack import m7_corpus
from reference_stack.fakes import ScriptedIntentClient, build_context
from reference_stack.stack import SERVICE_ROOT

from app.runtime.intent_echo import echo_problems, explain
from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.analytics_intent import AnalyticalIntent

DOCUMENT = SemanticRegistry(SERVICE_ROOT / "semantic_registry").get_certified("sales-core", "v1")
ONTOLOGY = build_context(DOCUMENT)[1]


def _intent(model_question: str) -> AnalyticalIntent:
    """The intent the scripted model proposes for a question (so a different question can be paired with it)."""
    reply = ScriptedIntentClient("req-1").complete_json(prompt=f'Request: "{model_question}"', schema={}, max_tokens=1)
    return AnalyticalIntent.model_validate(reply)


def test_every_valid_corpus_question_agrees_with_its_intent():
    cases = [c for c in json.loads(m7_corpus.CORPUS.read_text())["cases"] if c["kind"] == "answer"]
    assert len(cases) == 60
    wrong = [(c["question"], echo_problems(c["question"], _intent(c["question"]), ONTOLOGY)) for c in cases]
    assert [w for w in wrong if w[1]] == []


@pytest.mark.parametrize(
    ("question", "model_question", "expected"),
    [
        ("Show total profit", "What is total revenue", "metric_not_in_question:revenue"),
        ("What is the total number of customers", "What is total revenue", "metric_not_in_question:revenue"),
        ("Total revenue per customer", "What is total revenue", "unrecognized_grouping:customer"),
        ("Revenue by month for each region", "Show monthly revenue", "unrecognized_grouping:region"),
        ("Revenue by month", "Revenue by status", "grouping_not_in_question:status"),
        ("Revenue by status", "Show monthly revenue", "question_groups_by:status_but_intent_does_not"),
        ("Revenue by status", "What is total revenue", "question_groups_by:status_but_intent_does_not"),
        ("Show total", "What is total revenue", "metric_not_in_question:revenue"),
        (None, "What is total revenue", "no_question"),
    ],
)
def test_a_mismatch_between_question_and_intent_is_named(question, model_question, expected):
    assert expected in echo_problems(question, _intent(model_question), ONTOLOGY)


def test_a_filter_value_or_a_time_word_names_its_dimension():
    assert echo_problems("Revenue for refunded orders", _intent("revenue for refunded orders"), ONTOLOGY) == []
    assert echo_problems("Revenue each month", _intent("Show monthly revenue"), ONTOLOGY) == []
    assert echo_problems("Revenue by Status!", _intent("Revenue by status"), ONTOLOGY) == []
    assert echo_problems("revenue across statuses", _intent("Revenue by status"), ONTOLOGY) == []


def test_the_explanation_names_concepts_and_carries_no_content():
    text = explain(["unrecognized_grouping:region", "metric_not_in_question:revenue"])
    assert text.startswith("The question and the interpreted request do not match")
    assert "region" in text and "SELECT" not in text and len(text) < 300


def test_a_hostile_grouping_word_is_reduced_to_safe_characters():
    problems = echo_problems("revenue by <script>alert(1)</script>", _intent("Revenue by status"), ONTOLOGY)
    assert all("<" not in p and ">" not in p and "(" not in p for p in problems)


def test_the_pipeline_refuses_with_a_reason_and_runs_no_query(tmp_path):
    from reference_stack.stack import build_stack

    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    reply = stack.service().analyze(
        who, purpose="analytics", idempotency_key="echo-key-000001", request_text="Show total profit"
    )
    outcome = reply.outcome
    assert outcome.outcome == "refuse" and outcome.reason_code == "unsupported_request"
    assert "metric not in question" in outcome.explanation and outcome.remediation
    assert stack.executed_sql == []


def test_the_check_can_be_switched_off_only_where_the_node_is_built(tmp_path):
    import inspect

    from app.runtime.ontology_node import ontology_resolution_node

    assert inspect.signature(ontology_resolution_node).parameters["echo_check"].default is True
