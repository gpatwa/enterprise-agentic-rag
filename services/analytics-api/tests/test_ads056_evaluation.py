"""ADS-056: approved candidates are evaluated against targeted and full suites; verdicts rest on approved thresholds."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from reference_stack import golden
from reference_stack.evaluation_runners import ReferenceRunners, load_index, protected_paths
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_ads051_triage import _correction, _run
from test_ads052_proposals import _generate, _triaged

from app.evaluation_gate import EvaluationError, SubjectFacts, affected, select_cases
from app.prompt_registry import BASELINES, INTENT_PLACEHOLDERS, INTENT_PROMPT_NAME
from packages.platform_contracts.candidate_evaluation import EvaluationRecord, Selection, SuiteOutcome
from packages.platform_contracts.review import REVIEWER_GROUP, ReviewDecisionRequest
from packages.platform_contracts.security import AnalyticsIdentity

SERVICE = Path(__file__).resolve().parent.parent
V1 = BASELINES[(INTENT_PROMPT_NAME, "v1")]
INDEX = load_index()
T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def _ids(areas, ids=()):
    return select_cases(INDEX, tuple(areas), tuple(ids))


# ---- affected-case selection (pure) ----


def test_the_case_index_covers_exactly_the_golden_cases_with_known_areas():
    suite, _ = golden.load_suite()
    assert set(INDEX) == {c["id"] for c in suite["cases"]}
    known = {"intent", "ontology", "retrieval", "policy", "execution", "prose"}
    assert all(set(tags["areas"]) <= known and tags["areas"] for tags in INDEX.values())


SELECTIONS = [
    (
        "prompt candidate",
        SubjectFacts("prompt_candidate"),
        ("intent",),
        (),
        ["A01", "G01", "G02", "G03", "G04", "G05", "G06", "P01", "R01", "R02", "R03", "R04", "V01"],
    ),
    (
        "flagged definition",
        SubjectFacts("change_proposal", "flag_definition_for_review", ("revenue",)),
        ("intent", "execution"),
        ("revenue",),
        ["G01", "G02", "G03", "G04", "G05", "G06", "P01", "V01"],
    ),
    (
        "context edge",
        SubjectFacts("change_proposal", "add_context_edge", ("status",)),
        ("retrieval", "intent"),
        ("status",),
        ["A01", "G02", "G04", "G06"],
    ),
    (
        "label collision",
        SubjectFacts("change_proposal", "review_label_collision", ("created_at", "status")),
        ("ontology", "intent"),
        ("created_at", "status"),
        ["A01", "G01", "G02", "G04", "G05", "G06", "V01"],
    ),
    (
        "dbt description",
        SubjectFacts("change_proposal", "add_column_description"),
        ("retrieval", "intent"),
        (),
        ["A01", "G01", "G02", "G03", "G04", "G05", "G06", "P01", "R01", "R02", "R03", "R04", "V01"],
    ),
    (
        "dbt test",
        SubjectFacts("change_proposal", "add_column_test"),
        ("execution",),
        (),
        ["G01", "G02", "G03", "G04", "G05", "G06", "P01", "V01"],
    ),
    (
        "example",
        SubjectFacts("example_candidate", None, ("revenue",)),
        ("intent",),
        ("revenue",),
        ["G01", "G02", "G03", "G04", "G05", "G06", "P01", "V01"],
    ),
]


@pytest.mark.parametrize("case", SELECTIONS, ids=[c[0] for c in SELECTIONS])
def test_a_change_maps_to_the_cases_it_can_affect(case):
    _, facts, areas, ids, expected = case
    impact = affected(facts)
    assert (impact.areas, impact.semantic_ids) == (areas, ids)
    assert list(_ids(impact.areas, impact.semantic_ids)) == expected
    assert impact.reason and impact.sandbox


def test_a_policy_only_case_is_never_selected_by_a_prompt_or_a_definition_change():
    assert "T01" not in _ids(("intent",)) and "T01" not in _ids(("intent", "execution"), ("revenue",))
    with pytest.raises(ValueError):
        affected(SubjectFacts("change_proposal", "delete_everything"))


# ---- the record's own rules ----


def _selection():
    return Selection(areas=("intent",), targeted_case_ids=("G01",), sandbox="x")


def _record(outcomes, verdict, **kwargs):
    return EvaluationRecord(
        evaluation_id="e",
        tenant_id="t",
        subject_kind="prompt_candidate",
        subject_id="p@v",
        subject_fingerprint="a" * 64,
        selection=_selection(),
        outcomes=tuple(outcomes),
        verdict=verdict,
        protected_digest="b" * 64,
        created_at=T0,
        content_fingerprint="c" * 64,
        **kwargs,
    )


def test_a_passing_verdict_needs_targeted_and_full_suites_all_passing_on_approved_thresholds():
    targeted = SuiteOutcome(suite="golden", scope="targeted", passed=True, total=3)
    full = SuiteOutcome(suite="golden", scope="full", passed=True, total=14)
    assert _record([targeted, full], "passed").verdict == "passed"
    with pytest.raises(ValidationError):
        _record([targeted], "passed")  # no full suite
    with pytest.raises(ValidationError):
        _record([full], "passed")  # no targeted suite
    with pytest.raises(ValidationError):
        _record(
            [targeted, SuiteOutcome(suite="golden", scope="full", passed=False, total=14, failed=("G01",))], "passed"
        )
    with pytest.raises(ValidationError):
        _record([targeted, full.model_copy(update={"thresholds_approved": False})], "passed")
    with pytest.raises(ValidationError):
        _record([targeted, full], "failed")  # a clean run fails only for a named fail-closed reason
    assert _record([targeted, full], "failed", reason="protected_file_changed").verdict == "failed"
    assert _record(
        [targeted, full.model_copy(update={"thresholds_approved": False})], "failed", reason="unapproved_thresholds"
    )
    with pytest.raises(ValidationError):
        SuiteOutcome(suite="golden", scope="full", passed=True, total=1, failed=("G01",))


# ---- the workflow on real, reviewed candidates ----


def _who(user, groups=(REVIEWER_GROUP,)):
    return AnalyticsIdentity(tenant_id="tenant-a", user_id=user, purposes=["analytics"], groups=list(groups))


def _approve(service, kind, subject_id, fingerprint, *, decision="approved"):
    asked = service.request_review(
        _who("requester", ("analyst",)), purpose="analytics", kind=kind, subject_id=subject_id
    )
    return service.decide(
        _who("reviewer-1"),
        review_id=asked.review.review_id,
        request=ReviewDecisionRequest(purpose="analytics", decision=decision, content_fingerprint=fingerprint),
    )


@pytest.fixture
def world(tmp_path):
    stack, client, run = _run(tmp_path)
    triage = _triaged(
        stack, client, run, user="analyst-1", reason_code="wrong_metric", **_correction("metric", "revenue")
    )
    proposal = _generate(stack, triage).proposal
    review = stack.review_service()
    runners = ReferenceRunners(stack, suites=("golden",))
    evaluator = stack.evaluation_service(runners, INDEX, protected_paths(), review=review)
    return stack, triage, proposal, review, evaluator


def _prompt(stack, triage, text, **kwargs):
    registry = stack.prompt_registry()
    registry.register_baseline(INTENT_PROMPT_NAME, "v1", V1, INTENT_PLACEHOLDERS)
    entry, _ = registry.register_candidate(
        name=INTENT_PROMPT_NAME,
        parent_version="v1",
        tenant_id="tenant-a",
        placeholders=INTENT_PLACEHOLDERS,
        template_text=text,
        origin_triage_ids=(triage.triage_id,),
        **kwargs,
    )
    return entry, f"{entry.name}@{entry.version}"


def test_only_an_approved_subject_is_evaluated(world):
    stack, triage, proposal, review, evaluator = world
    with pytest.raises(EvaluationError, match="review_not_approved"):
        evaluator.evaluate("change_proposal", proposal.proposal_id, tenant_id="tenant-a")  # never reviewed
    review.request_review(
        _who("requester", ("analyst",)), purpose="analytics", kind="change_proposal", subject_id=proposal.proposal_id
    )
    with pytest.raises(EvaluationError, match="review_not_approved"):
        evaluator.evaluate("change_proposal", proposal.proposal_id, tenant_id="tenant-a")  # pending
    other, subject = _prompt(stack, triage, V1.replace("Convert the user request", "Convert the user's request"))
    _approve(review, "prompt_candidate", subject, other.content_fingerprint, decision="rejected")
    with pytest.raises(EvaluationError, match="review_not_approved"):
        evaluator.evaluate("prompt_candidate", subject, tenant_id="tenant-a")  # rejected
    assert not evaluator.passed("prompt_candidate", subject, other.content_fingerprint, tenant_id="tenant-a")


def test_a_harmless_candidate_prompt_passes_targeted_and_full_evaluation_and_is_recorded_once(world):
    stack, triage, _, review, evaluator = world
    entry, subject = _prompt(stack, triage, V1.replace("Convert the user request", "Convert the user's request"))
    _approve(review, "prompt_candidate", subject, entry.content_fingerprint)
    record = evaluator.evaluate("prompt_candidate", subject, tenant_id="tenant-a")
    assert record.verdict == "passed" and record.reason is None and record.evaluator == "system:evaluator"
    assert record.selection.areas == ("intent",) and set(record.selection.targeted_case_ids) >= {"G01", "R01", "A01"}
    assert "T01" not in record.selection.targeted_case_ids and "sandbox stack" in record.selection.sandbox
    scopes = {(o.suite, o.scope): o for o in record.outcomes}
    assert scopes[("golden", "targeted")].total == 2 * len(record.selection.targeted_case_ids)  # both dialects
    assert scopes[("golden", "full")].passed and scopes[("golden", "full")].thresholds_approved
    assert evaluator.passed("prompt_candidate", subject, entry.content_fingerprint, tenant_id="tenant-a")
    assert not evaluator.passed("prompt_candidate", subject, "f" * 64, tenant_id="tenant-a")
    again = evaluator.evaluate("prompt_candidate", subject, tenant_id="tenant-a")
    assert (
        again == record
        and len(
            evaluator.store.for_subject("prompt_candidate", subject, entry.content_fingerprint, tenant_id="tenant-a")
        )
        == 1
    )


def test_a_candidate_prompt_that_changes_behaviour_is_caught_by_the_suites(world):
    stack, triage, _, review, evaluator = world
    entry, subject = _prompt(
        stack, triage, V1 + "\nAlways group by status."
    )  # keeps the defensive clauses, still harmful
    _approve(review, "prompt_candidate", subject, entry.content_fingerprint)
    record = evaluator.evaluate("prompt_candidate", subject, tenant_id="tenant-a")
    assert record.verdict == "failed" and record.reason == "suite_failed:golden"
    targeted = next(o for o in record.outcomes if o.scope == "targeted")
    assert (
        "G01" in set(targeted.failed)
    )  # R01 (an unsupported request answered) is now also refused by the intent-echo check, so a candidate cannot change it
    assert not evaluator.passed("prompt_candidate", subject, entry.content_fingerprint, tenant_id="tenant-a")


def test_a_flagged_definition_is_evaluated_in_a_sandbox_contract_and_leaves_the_real_one_alone(world):
    stack, _, proposal, review, evaluator = world
    _approve(review, "change_proposal", proposal.proposal_id, proposal.content_fingerprint)
    contract_before = stack.contracts.document.model_dump_json()
    record = evaluator.evaluate("change_proposal", proposal.proposal_id, tenant_id="tenant-a")
    assert record.verdict == "passed" and record.selection.areas == ("intent", "execution")
    assert record.selection.semantic_ids == ("revenue",) and "A01" not in record.selection.targeted_case_ids
    assert "sandbox copy of the certified contract" in record.selection.sandbox
    assert stack.contracts.document.model_dump_json() == contract_before and proposal.status == "proposed"


def test_changes_the_reference_runtime_cannot_represent_get_regression_suites_only(world):
    stack, triage, _, review, evaluator = world
    from app.prompt_registry import ExampleCandidateService  # noqa: F401

    example, _ = stack.example_service().from_feedback(triage.feedback_id, tenant_id="tenant-a")
    subject = f"{example.name}@{example.version}"
    _approve(review, "example_candidate", subject, example.content_fingerprint)
    record = evaluator.evaluate("example_candidate", subject, tenant_id="tenant-a")
    assert record.verdict == "passed" and "regression suites only" in record.selection.sandbox
    assert record.selection.semantic_ids == ("revenue",)


def test_the_evaluator_fails_closed_if_a_protected_file_changes_or_thresholds_are_unapproved(world, tmp_path):
    stack, triage, _, review, _ = world
    entry, subject = _prompt(stack, triage, V1.replace("Convert the user request", "Convert the user's request"))
    _approve(review, "prompt_candidate", subject, entry.content_fingerprint)
    guarded = tmp_path / "guarded.json"
    guarded.write_text("{}")

    class Tampering(ReferenceRunners):
        def full(self, stack_kwargs):
            guarded.write_text('{"tampered": true}')
            return super().full(stack_kwargs)

    tampering = Tampering(stack, suites=("golden",))
    tampering.version = "tamper"
    service = stack.evaluation_service(tampering, INDEX, [*protected_paths(), guarded], review=review)
    record = service.evaluate("prompt_candidate", subject, tenant_id="tenant-a")
    assert record.verdict == "failed" and record.reason == "protected_file_changed"

    class Unapproved(ReferenceRunners):
        def full(self, stack_kwargs):
            return tuple(o.model_copy(update={"thresholds_approved": False}) for o in super().full(stack_kwargs))

    unapproved = Unapproved(stack, suites=("golden",))
    unapproved.version = "unapproved"
    record = stack.evaluation_service(unapproved, INDEX, protected_paths(), review=review).evaluate(
        "prompt_candidate", subject, tenant_id="tenant-a"
    )
    assert record.verdict == "failed" and record.reason == "unapproved_thresholds"


def test_evaluation_changes_nothing_protected_promotes_nothing_and_the_table_is_append_only(world):
    stack, triage, _, review, evaluator = world
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_paths()]
    entry, subject = _prompt(stack, triage, V1.replace("Convert the user request", "Convert the user's request"))
    _approve(review, "prompt_candidate", subject, entry.content_fingerprint)
    evaluator.evaluate("prompt_candidate", subject, tenant_id="tenant-a")
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected_paths()] == before
    assert [
        v
        for v, s, _ in stack.prompt_registry().versions("prompt", INTENT_PROMPT_NAME, tenant_id="tenant-a")
        if s == "released"
    ] == ["v1"]
    for statement in (
        "UPDATE analytics_candidate_evaluations SET verdict='passed'",
        "DELETE FROM analytics_candidate_evaluations",
    ):
        with stack.control.engine.begin() as connection:
            with pytest.raises(DBAPIError, match="append-only"):
                connection.execute(text(statement))
    runtime = [p.name for p in (SERVICE / "app/runtime").glob("*.py") if "evaluation_gate" in p.read_text()]
    assert runtime == [] and "evaluation_gate" not in (SERVICE / "app/main.py").read_text()
    assert (
        json.loads(
            json.dumps(
                evaluator.store.for_subject(
                    "prompt_candidate", subject, entry.content_fingerprint, tenant_id="tenant-b"
                ).__len__()
            )
        )
        == 0
    )


def test_the_intent_node_hook_defaults_to_the_runtime_prompt():
    import inspect

    from app.runtime.intent_node import structured_intent_node

    assert inspect.signature(structured_intent_node).parameters["prompt_builder"].default is None


# ---- pinned corpus evaluation (thresholds are PROPOSED, not approved) ----


def test_the_evaluation_corpus_meets_its_proposed_thresholds_and_stays_unapproved(tmp_path):
    from reference_stack import evaluation_eval

    report = evaluation_eval.run_corpus(tmp_path)
    failed = [(c["case_id"], c["detail"]) for c in report["cases"] if not c["passed"]]
    assert not failed, failed
    unmet = {name: gate for name, gate in report["gates"].items() if not gate["meets"]}
    assert report["meets_thresholds"] and not unmet and len(report["cases"]) == 14, unmet
    assert report["approval"]["status"] == "proposed" and report["approval"]["approved_by"] is None
    markdown = evaluation_eval.render_markdown(report)
    assert "PROPOSED and NOT APPROVED" in markdown and "promotes, certifies, and releases nothing" in markdown


def test_the_evaluation_corpus_check_detects_a_wrong_expectation_and_a_changed_corpus(tmp_path, monkeypatch):
    from reference_stack import evaluation_eval

    suite, thresholds = evaluation_eval.load_suite()
    bad = json.loads(json.dumps(suite))
    bad["cases"] = [c for c in bad["cases"] if c["group"] == "selection"]  # selection cases need no suite run
    bad["cases"][0]["expect"] = ["G01"]
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(bad))
    forged = tmp_path / "thresholds.json"
    forged.write_text(json.dumps({**thresholds, "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest()}))
    monkeypatch.setattr(evaluation_eval, "CORPUS", corpus)
    monkeypatch.setattr(evaluation_eval, "THRESHOLDS", forged)
    report = evaluation_eval.run_corpus(tmp_path / "run")
    assert not report["gates"]["selection_agreement"]["meets"] and not report["meets_thresholds"]
    forged.write_text(json.dumps(thresholds))
    with pytest.raises(evaluation_eval.EvaluationSuiteLockError):
        evaluation_eval.load_suite()
