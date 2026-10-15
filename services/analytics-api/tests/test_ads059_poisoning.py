"""ADS-059: hostile feedback cannot change goldens, policy, or production behaviour."""

from __future__ import annotations

import hashlib
import json

import pytest
from reference_stack import poisoning_eval

from app.review import rules as review_rules
from app.review import service as review_service


@pytest.fixture(scope="module")
def report(poisoning_report):
    return poisoning_report


def test_the_poisoning_corpus_meets_its_proposed_thresholds_and_stays_unapproved(report):
    failed = [(c["case_id"], c["detail"]) for c in report["cases"] if not c["passed"]]
    assert not failed, failed
    unmet = {name: gate for name, gate in report["gates"].items() if not gate["meets"]}
    assert report["meets_thresholds"] and not unmet and len(report["cases"]) == 26, unmet
    assert report["approval"]["status"] == "proposed" and report["approval"]["approved_by"] is None
    markdown = poisoning_eval.render_markdown(report)
    assert "PROPOSED and NOT APPROVED" in markdown and "not an independent review" in markdown


def test_the_corpus_covers_every_stage_of_the_loop(report):
    groups = {c["group"] for c in report["cases"]}
    assert groups == {"intake", "free_text", "volume", "contract", "approval", "chain"}
    by_op = {c["op"] for c in report["cases"]}
    assert {
        "feedback",
        "note_injection",
        "feedback_flood",
        "prompt_clauses",
        "patch",
        "dbt_edit",
        "example",
        "review_decide",
        "chain",
    } <= by_op
    assert len({c["case_id"] for c in report["cases"]}) == len(report["cases"])


def test_every_attack_class_is_blocked_and_nothing_protected_moved(report):
    gates = report["gates"]
    for name in ("intake_block_rate", "contract_block_rate", "approval_block_rate"):
        assert gates[name]["value"] == 1.0, name
    assert gates["barred_approvals"]["value"] == 0 and gates["release_mutations"]["value"] == 0
    assert gates["protected_file_writes"]["value"] == 0 and gates["pipeline_wired_into_runtime"]["value"] == 0
    assert gates["production_answer_unchanged"]["value"] == 1.0 and gates["golden_thresholds_still_met"]["value"] == 1.0


def test_hostile_free_text_is_inert_and_a_flood_only_adds_support(report):
    cases = {c["case_id"]: c for c in report["cases"]}
    assert cases["X09"]["got"] == "inert"
    assert cases["X10"]["got"] == "flood:proposals=1:approved_reviews=0"
    assert report["gates"]["flood_amplification"]["value"] == 1


def test_a_compromised_reviewer_is_stopped_by_the_evaluation_gate_not_by_the_review(report):
    case = next(c for c in report["cases"] if c["case_id"] == "X23")
    assert case["got"] == "refused:evaluation_not_passed"


def test_the_evaluation_fails_when_a_defence_is_weakened(tmp_path, monkeypatch):
    """The corpus must be able to fail: with the automated-identity check off, an automated approval gets through."""
    monkeypatch.setattr(review_rules, "is_automated", lambda user_id: False)
    monkeypatch.setattr(review_service, "is_automated", lambda user_id: False)
    report = poisoning_eval.run_corpus(tmp_path)
    cases = {c["case_id"]: c for c in report["cases"]}
    assert cases["X20"]["got"] == "approved" and not cases["X20"]["passed"]
    assert not report["meets_thresholds"]
    assert not report["gates"]["approval_block_rate"]["meets"] and not report["gates"]["barred_approvals"]["meets"]
    assert report["gates"]["intake_block_rate"]["meets"]  # other defences still held


def test_a_wrong_expectation_or_a_changed_corpus_is_detected(tmp_path, monkeypatch, report):
    """No corpus re-run: the expectation change is scored against the shared run, and the digest lock is exercised directly."""
    from conftest import agreement_with

    case = next(c for c in report["cases"] if c["case_id"] == "X01")
    assert case["got"] != "accepted" and case["passed"]  # the pipeline rejected SQL in a correction
    assert agreement_with(report, "X01", "accepted") < 1.0 and report["gates"]["barred_approvals"]["meets"]
    suite, thresholds = poisoning_eval.load_suite()
    bad = json.loads(json.dumps(suite))
    next(c for c in bad["cases"] if c["id"] == "X01")["expect"] = "accepted"  # claim SQL in a correction is fine
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(bad))
    forged = tmp_path / "thresholds.json"
    forged.write_text(json.dumps({**thresholds, "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest()}))
    monkeypatch.setattr(poisoning_eval, "CORPUS", corpus)
    monkeypatch.setattr(poisoning_eval, "THRESHOLDS", forged)
    loaded, _ = poisoning_eval.load_suite()
    assert next(c for c in loaded["cases"] if c["id"] == "X01")["expect"] == "accepted"
    forged.write_text(json.dumps(thresholds))
    with pytest.raises(poisoning_eval.PoisoningSuiteLockError):
        poisoning_eval.load_suite()
