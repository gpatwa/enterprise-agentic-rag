"""ADS-073: the pipeline abstains instead of guessing, says why, and the evaluation can fail."""

from __future__ import annotations

import copy
import json

import pytest
from reference_stack import abstention_eval as ev
from reference_stack.stack import build_stack

THRESHOLDS = json.loads(ev.THRESHOLDS.read_text())
CORPUS = json.loads(ev.CORPUS.read_bytes())


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return ev.run_abstention(workdir=tmp_path_factory.mktemp("abstain"))


def test_the_corpus_is_pinned_and_generated(tmp_path):
    assert ev.corpus_digest(ev.CORPUS.read_bytes()) == THRESHOLDS["corpus_sha256"]
    assert ev.render_corpus(ev.build_corpus()) == ev.CORPUS.read_bytes()
    groups = {c["group"] for c in CORPUS["cases"]}
    assert {"unsupported", "hostile", "malformed", "uncertified", "cross_tenant", "ambiguous", "valid"} <= groups


def test_the_pipeline_meets_the_proposed_gates(report):
    assert report["ok"], [(n, g["value"]) for n, g in report["gates"].items() if not g["meets"]]
    assert not [c for c in report["cases"] if not c["ok"]]
    assert all(c["executed_queries"] == 0 for c in report["cases"] if c["expected"] != "answer")
    assert THRESHOLDS["approval"]["status"] == "proposed"


def test_an_unsupported_request_is_a_refusal_with_its_own_reason_not_a_retryable_outage(tmp_path):
    from unittest import mock

    from reference_stack import stack as stack_module

    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    with mock.patch.object(stack_module, "ScriptedIntentClient", ev._FixedModel({"unsupported_request": True})):
        response = stack.service().analyze(
            who, purpose="analytics", idempotency_key="unsup-key-000001", request_text="Tell me a joke"
        )
    outcome = response.outcome
    assert outcome.outcome == "refuse" and outcome.reason_code == "unsupported_request" and outcome.remediation
    assert stack.executed_sql == []


def test_malformed_model_output_is_still_a_failed_planning_outcome(tmp_path):
    from unittest import mock

    from reference_stack import stack as stack_module

    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    with mock.patch.object(stack_module, "ScriptedIntentClient", ev._FixedModel({"foo": 1})):
        outcome = (
            stack.service()
            .analyze(who, purpose="analytics", idempotency_key="malf-key-0000001", request_text="Show revenue")
            .outcome
        )
    assert outcome.outcome == "failed" and outcome.error_code == "planner_unavailable"


def test_reverting_the_unsupported_fix_fails_the_reason_gate(monkeypatch, tmp_path):
    from app.runtime import analyze_service

    original = analyze_service.GovernedAnalyzeService._terminal

    def old_behaviour(self, state, base):
        if state.terminal_outcome.kind == "failed" and any(e.code == "unsupported_request" for e in state.errors):
            return analyze_service.AnalyticsFailedOutcome(
                **base, error_code="planner_unavailable", message="The request could not be planned.", retryable=True
            )
        return original(self, state, base)

    monkeypatch.setattr(analyze_service.GovernedAnalyzeService, "_terminal", old_behaviour)
    report = ev.run_abstention(workdir=tmp_path)
    assert not report["gates"]["unsupported_reason_precision"]["meets"] and not report["ok"]


def test_an_answer_where_the_corpus_requires_abstention_is_a_guess(tmp_path):
    corpus = copy.deepcopy(CORPUS)
    victim = next(c for c in corpus["cases"] if c["id"] == "V01")
    victim["expect"] = "abstain"  # the pipeline answers a valid question, so this expectation counts it as a guess
    report = ev.run_abstention(corpus=corpus, workdir=tmp_path)
    assert report["gates"]["guess_rate"]["value"] >= 1 and not report["gates"]["guess_rate"]["meets"]


def test_a_valid_question_that_is_refused_is_a_false_abstention(tmp_path):
    corpus = copy.deepcopy(CORPUS)
    victim = next(c for c in corpus["cases"] if c["id"] == "V01")
    victim["model_output"] = {"unsupported_request": True}
    report = ev.run_abstention(corpus=corpus, workdir=tmp_path)
    assert (
        report["gates"]["false_abstention_rate"]["value"] > 0.05
        and not report["gates"]["false_abstention_rate"]["meets"]
    )


def test_a_changed_corpus_is_refused_until_the_digest_is_updated(monkeypatch, tmp_path):
    tampered = tmp_path / "corpus.json"
    tampered.write_bytes(ev.CORPUS.read_bytes() + b"\n")
    monkeypatch.setattr(ev, "CORPUS", tampered)
    with pytest.raises(RuntimeError, match="digest"):
        ev.run_abstention()


def test_the_report_states_the_open_gap_and_what_is_not_measured(report):
    text = ev.render_markdown(report)
    assert report["open_gap"]["answered_by_scripted_model"] == 0 and "Near-miss questions" in text
    assert "NOT APPROVED" in text and "real_model_abstention" in text


def test_without_the_intent_echo_check_the_near_miss_questions_are_answered(monkeypatch, tmp_path):
    import app.runtime.ontology_node as node

    monkeypatch.setattr(node, "echo_problems", lambda *args, **kwargs: [])
    report = ev.run_abstention(workdir=tmp_path)
    assert report["gates"]["near_miss_answered"]["value"] == len(CORPUS["near_miss_questions"]) and not report["ok"]
