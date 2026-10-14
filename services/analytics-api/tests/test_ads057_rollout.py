"""ADS-057: shadow, canary, promotion, and automatic rollback without losing evidence or run state."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from reference_stack.evaluation_runners import ReferenceRunners, load_index, protected_paths
from reference_stack.rollout_observers import ReferenceObservers, approved_for_test, load_policy
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_ads051_triage import _correction, _run
from test_ads052_proposals import _triaged

from app.prompt_registry import BASELINES, INTENT_PLACEHOLDERS, INTENT_PROMPT_NAME, RegistryError
from app.rollout import RolloutError
from packages.platform_contracts.prompt_registry import PromptTemplate
from packages.platform_contracts.review import REVIEWER_GROUP, ReviewDecisionRequest
from packages.platform_contracts.rollout import RolloutPolicy
from packages.platform_contracts.security import AnalyticsIdentity

SERVICE = Path(__file__).resolve().parent.parent
V1 = BASELINES[(INTENT_PROMPT_NAME, "v1")]
HARMLESS = V1.replace("Convert the user request", "Convert the user's request")
T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
POLICY = approved_for_test(load_policy())


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _who(user, groups=("analyst",), purposes=("analytics",)):
    return AnalyticsIdentity(tenant_id="tenant-a", user_id=user, purposes=list(purposes), groups=list(groups))


def _build(tmp_path, *, observers=None, policy=POLICY, text=HARMLESS, review=True, evaluate=True):
    stack, client, run = _run(tmp_path)
    triage = _triaged(
        stack, client, run, user="analyst-1", reason_code="wrong_metric", **_correction("metric", "revenue")
    )
    registry = stack.prompt_registry()
    registry.register_baseline(INTENT_PROMPT_NAME, "v1", V1, INTENT_PLACEHOLDERS)
    entry, _ = registry.register_candidate(
        name=INTENT_PROMPT_NAME,
        parent_version="v1",
        tenant_id="tenant-a",
        placeholders=INTENT_PLACEHOLDERS,
        template_text=text,
        origin_triage_ids=(triage.triage_id,),
    )
    subject = f"{entry.name}@{entry.version}"
    clock = Clock()
    reviews = stack.review_service(now=clock)
    if review:
        asked = reviews.request_review(
            _who("requester"), purpose="analytics", kind="prompt_candidate", subject_id=subject
        )
        reviews.decide(
            _who("reviewer-1", (REVIEWER_GROUP,)),
            review_id=asked.review.review_id,
            request=ReviewDecisionRequest(
                purpose="analytics", decision="approved", content_fingerprint=entry.content_fingerprint
            ),
        )
    evaluator = stack.evaluation_service(
        ReferenceRunners(stack, suites=("golden",)), load_index(), protected_paths(), review=reviews, now=clock
    )
    if evaluate:
        evaluator.evaluate("prompt_candidate", subject, tenant_id="tenant-a")
    controller = stack.rollout_controller(
        policy, observers or ReferenceObservers(), review=reviews, evaluations=evaluator, now=clock
    )
    return stack, entry, subject, clock, controller


def _to_canary(controller, rollout_id):
    status = controller.advance(rollout_id, tenant_id="tenant-a")  # shadow
    for _ in POLICY.canary_fractions:
        status = controller.advance(rollout_id, tenant_id="tenant-a")
    return status


# ---- the contract ----


def test_the_rollout_policy_must_be_sane_and_the_repository_policy_is_not_approved():
    assert load_policy().approval.status == "proposed" and POLICY.approval.status == "approved"
    base = load_policy().model_dump()
    for bad in (
        {"canary_fractions": [0.5, 0.1]},
        {"canary_fractions": [0.1, 0.1]},
        {"canary_fractions": [0.0]},
        {"canary_fractions": [1.5]},
        {"shadow_min_agreement": 1.5},
        {"approval": {"status": "approved"}},
    ):
        with pytest.raises(ValidationError):
            RolloutPolicy.model_validate({**base, **bad})


def test_a_released_prompt_is_either_the_baseline_or_a_recorded_promotion_and_nothing_else():
    import dataclasses  # noqa: F401

    fields = dict(
        name="intent-prompt",
        version="v2",
        status="released",
        scope="system",
        template_text=HARMLESS,
        placeholders=INTENT_PLACEHOLDERS,
        text_fingerprint=hashlib.sha256(HARMLESS.encode()).hexdigest(),
        parent_version="v1",
        created_at=T0,
        content_fingerprint="a" * 64,
    )
    candidate = "candidate-" + fields["text_fingerprint"][:12]
    assert (
        PromptTemplate(**fields, created_by="system:promotion", promoted_from=candidate, promotion_id="r1").status
        == "released"
    )
    for bad in (
        dict(created_by="system:promotion"),
        dict(created_by="system:promotion", promoted_from=candidate),
        dict(created_by="system:promotion", promoted_from="v1", promotion_id="r1"),
        dict(created_by="system:candidate"),
        dict(created_by="system:baseline", promoted_from=candidate, promotion_id="r1"),
    ):
        with pytest.raises(ValidationError):
            PromptTemplate(**fields, **bad)


# ---- the gate to start ----


def test_a_rollout_only_starts_for_an_approved_evaluated_candidate_under_an_approved_policy(tmp_path):
    stack, entry, subject, clock, controller = _build(tmp_path)
    with pytest.raises(RolloutError, match="automated_identity"):
        controller.start(_who("system:release-bot"), purpose="analytics", subject_id=subject)
    with pytest.raises(RolloutError, match="purpose_not_authorized"):
        controller.start(_who("operator", purposes=("billing",)), purpose="analytics", subject_id=subject)
    with pytest.raises(RolloutError, match="not_promotable"):
        controller.start(_who("operator"), purpose="analytics", subject_id=subject, kind="change_proposal")
    with pytest.raises(RolloutError, match="not_promotable|subject_not_found|not_reviewable"):
        controller.start(_who("operator"), purpose="analytics", subject_id="intent-prompt@v1")
    proposed = stack.rollout_controller(
        load_policy(), ReferenceObservers(), review=controller.reviews, evaluations=controller.evaluations, now=clock
    )
    with pytest.raises(RolloutError, match="rollout_policy_not_approved"):
        proposed.start(_who("operator"), purpose="analytics", subject_id=subject)
    assert controller.start(_who("operator"), purpose="analytics", subject_id=subject).state == "evaluated"


def test_an_unreviewed_or_unevaluated_candidate_never_starts(tmp_path):
    _, _, subject, _, controller = _build(tmp_path, review=False, evaluate=False)
    with pytest.raises(RolloutError, match="review_not_approved"):
        controller.start(_who("operator"), purpose="analytics", subject_id=subject)
    _, _, subject2, _, controller2 = _build(tmp_path / "b", evaluate=False)
    with pytest.raises(RolloutError, match="evaluation_not_passed"):
        controller2.start(_who("operator"), purpose="analytics", subject_id=subject2)
    harmful = HARMLESS + "\nAlways group by status."
    _, _, subject3, _, controller3 = _build(tmp_path / "c", text=harmful)  # evaluation runs and fails
    with pytest.raises(RolloutError, match="evaluation_not_passed"):
        controller3.start(_who("operator"), purpose="analytics", subject_id=subject3)


# ---- the happy path ----


def test_shadow_canary_and_promotion_create_the_next_released_version_and_move_the_pointer(tmp_path):
    stack, entry, subject, clock, controller = _build(tmp_path)
    started = controller.start(_who("operator"), purpose="analytics", subject_id=subject)
    rid = started.record.rollout_id
    assert started.record.baseline_version == "v1" and controller.active_version(INTENT_PROMPT_NAME) == "v1"
    with pytest.raises(RolloutError, match="canary_incomplete"):
        controller.promote(rid, tenant_id="tenant-a")  # cannot skip the stages
    shadow = controller.advance(rid, tenant_id="tenant-a")
    assert shadow.state == "shadow" and shadow.events[-1].detail == {"agreement": 1.0, "total": 10}
    first = controller.advance(rid, tenant_id="tenant-a")
    assert first.state == "canary" and first.canary_passed == (0.1,)
    with pytest.raises(RolloutError, match="canary_incomplete"):
        controller.promote(rid, tenant_id="tenant-a")
    second = controller.advance(rid, tenant_id="tenant-a")
    assert second.canary_passed == (0.1, 0.5) and second.events[-1].detail["requests"] == 5
    promoted = controller.promote(rid, tenant_id="tenant-a")
    assert promoted.state == "promoted" and promoted.released_version == "v2"
    release = stack.prompt_registry().get("prompt", INTENT_PROMPT_NAME, "v2")
    assert (
        release.status == "released" and release.created_by == "system:promotion" and release.template_text == HARMLESS
    )
    assert release.promoted_from == entry.version and release.promotion_id == rid and release.parent_version == "v1"
    assert [(p.version, p.reason) for p in controller.store.pointer_history(INTENT_PROMPT_NAME)] == [
        ("v1", "baseline"),
        ("v2", "promoted"),
    ]
    assert controller.promote(rid, tenant_id="tenant-a") == promoted  # idempotent: one release, one pointer move
    assert [v for v, s, _ in stack.prompt_registry().versions("prompt", INTENT_PROMPT_NAME, status="released")] == [
        "v1",
        "v2",
    ]
    assert (
        controller.start(_who("operator"), purpose="analytics", subject_id=subject).state == "promoted"
    )  # same rollout
    assert controller.monitor(rid, tenant_id="tenant-a").events[-1].event_type == "monitor_ok"


# ---- automatic rollback ----


def test_a_shadow_disagreement_rolls_back_before_anything_is_released(tmp_path):
    stack, _, subject, _, controller = _build(tmp_path, observers=ReferenceObservers(shadow_fault=True))
    rid = controller.start(_who("operator"), purpose="analytics", subject_id=subject).record.rollout_id
    status = controller.advance(rid, tenant_id="tenant-a")
    assert status.state == "rolled_back" and status.rollback_reason == "shadow_disagreement"
    assert status.events[-1].actor == "system:rollout-controller" and status.events[-1].detail["agreement"] == 0.8
    assert controller.active_version(INTENT_PROMPT_NAME) == "v1"
    assert [v for v, s, _ in stack.prompt_registry().versions("prompt", INTENT_PROMPT_NAME, status="released")] == [
        "v1"
    ]
    with pytest.raises(RolloutError, match="rolled_back"):
        controller.promote(rid, tenant_id="tenant-a")


def test_a_canary_regression_rolls_back_and_never_releases(tmp_path):
    stack, _, subject, _, controller = _build(tmp_path, observers=ReferenceObservers(canary_faults={0.5: 1}))
    rid = controller.start(_who("operator"), purpose="analytics", subject_id=subject).record.rollout_id
    controller.advance(rid, tenant_id="tenant-a")
    assert controller.advance(rid, tenant_id="tenant-a").canary_passed == (0.1,)
    status = controller.advance(rid, tenant_id="tenant-a")
    assert status.state == "rolled_back" and status.rollback_reason == "canary_regression:0.5"
    assert controller.active_version(INTENT_PROMPT_NAME) == "v1"
    assert [v for v, s, _ in stack.prompt_registry().versions("prompt", INTENT_PROMPT_NAME, status="released")] == [
        "v1"
    ]


def test_a_regression_after_promotion_reverts_the_pointer_but_keeps_the_release_and_the_evidence(tmp_path):
    observers = ReferenceObservers()
    stack, _, subject, clock, controller = _build(tmp_path, observers=observers)
    client_runs = stack.control.engine
    rid = controller.start(_who("operator"), purpose="analytics", subject_id=subject).record.rollout_id
    _to_canary(controller, rid)
    controller.promote(rid, tenant_id="tenant-a")
    observers.monitor_fault = 2
    tables = (
        "analytics_agent_runs",
        "analytics_evidence_envelopes",
        "analytics_feedback",
        "analytics_feedback_triage",
        "analytics_reviews",
        "analytics_review_events",
        "analytics_candidate_evaluations",
        "analytics_rollout_events",
    )
    counts = lambda: [client_runs.connect().execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in tables]  # noqa: E731
    run_states = (
        client_runs.connect().execute(text("SELECT state_payload FROM analytics_agent_runs ORDER BY run_id")).fetchall()
    )
    before = counts()
    status = controller.monitor(rid, tenant_id="tenant-a")
    assert status.state == "rolled_back" and status.rollback_reason == "monitor_regression"
    assert controller.active_version(INTENT_PROMPT_NAME) == "v1"
    assert [(p.version, p.reason) for p in controller.store.pointer_history(INTENT_PROMPT_NAME)][-2:] == [
        ("v2", "promoted"),
        ("v1", "rollback:monitor_regression"),
    ]
    assert (
        stack.prompt_registry().get("prompt", INTENT_PROMPT_NAME, "v2").status == "released"
    )  # released versions are write-once
    after = counts()
    assert after[:-1] == before[:-1] and after[-1] == before[-1] + 1  # only the rollback event was added: nothing lost
    assert (
        client_runs.connect().execute(text("SELECT state_payload FROM analytics_agent_runs ORDER BY run_id")).fetchall()
        == run_states
    )


def test_a_stale_approval_or_a_lost_gate_rolls_the_rollout_back_instead_of_promoting(tmp_path):
    stack, _, subject, clock, controller = _build(tmp_path)
    rid = controller.start(_who("operator"), purpose="analytics", subject_id=subject).record.rollout_id
    _to_canary(controller, rid)
    clock.now += timedelta(hours=POLICY.approval_max_age_hours + 1)
    status = controller.promote(rid, tenant_id="tenant-a")
    assert status.state == "rolled_back" and status.rollback_reason == "gate_lost:approval_stale"
    assert [v for v, s, _ in stack.prompt_registry().versions("prompt", INTENT_PROMPT_NAME, status="released")] == [
        "v1"
    ]


def test_a_manual_rollback_is_audited_and_idempotent(tmp_path):
    _, _, subject, _, controller = _build(tmp_path)
    rid = controller.start(_who("operator"), purpose="analytics", subject_id=subject).record.rollout_id
    first = controller.rollback(rid, tenant_id="tenant-a", reason="operator_request", actor="operator")
    assert (
        first.state == "rolled_back"
        and first.events[-1].actor == "operator"
        and first.rollback_reason == "operator_request"
    )
    assert controller.rollback(rid, tenant_id="tenant-a", reason="again") == first


def test_a_candidate_derived_from_a_superseded_version_cannot_start(tmp_path):
    stack, entry, subject, clock, controller = _build(tmp_path)
    rid = controller.start(_who("operator"), purpose="analytics", subject_id=subject).record.rollout_id
    _to_canary(controller, rid)
    controller.promote(rid, tenant_id="tenant-a")  # v2 is now active
    other = stack.prompt_registry().register_candidate(
        name=INTENT_PROMPT_NAME,
        parent_version="v1",
        tenant_id="tenant-a",
        placeholders=INTENT_PLACEHOLDERS,
        template_text=HARMLESS.replace("Convert", "Please convert"),
    )[0]
    reviews = controller.reviews
    asked = reviews.request_review(
        _who("requester"), purpose="analytics", kind="prompt_candidate", subject_id=f"{other.name}@{other.version}"
    )
    reviews.decide(
        _who("reviewer-1", (REVIEWER_GROUP,)),
        review_id=asked.review.review_id,
        request=ReviewDecisionRequest(
            purpose="analytics", decision="approved", content_fingerprint=other.content_fingerprint
        ),
    )
    controller.evaluations.evaluate("prompt_candidate", f"{other.name}@{other.version}", tenant_id="tenant-a")
    with pytest.raises(RolloutError, match="stale_parent"):
        controller.start(_who("operator"), purpose="analytics", subject_id=f"{other.name}@{other.version}")


# ---- isolation ----


def test_rollouts_change_nothing_protected_are_tenant_scoped_append_only_and_unwired(tmp_path):
    stack, _, subject, _, controller = _build(tmp_path)
    paths = protected_paths()
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    rid = controller.start(_who("operator"), purpose="analytics", subject_id=subject).record.rollout_id
    _to_canary(controller, rid)
    controller.promote(rid, tenant_id="tenant-a")
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths] == before
    with pytest.raises(RolloutError, match="rollout_not_found"):
        controller.status(rid, tenant_id="tenant-b")
    for table in ("analytics_rollouts", "analytics_rollout_events", "analytics_release_pointer"):
        for statement in (
            f"UPDATE {table} SET seq=seq"
            if table != "analytics_rollouts"
            else f"UPDATE {table} SET tenant_id=tenant_id",
            f"DELETE FROM {table}",
        ):
            with stack.control.engine.begin() as connection:
                with pytest.raises(DBAPIError, match="append-only"):
                    connection.execute(text(statement))
    runtime = [
        p.name
        for p in (SERVICE / "app/runtime").glob("*.py")
        if "app.rollout" in p.read_text() or "release_pointer" in p.read_text()
    ]
    assert runtime == [] and "app.rollout" not in (SERVICE / "app/main.py").read_text()
    with pytest.raises(RegistryError):  # a released version cannot be created except by promotion of a candidate
        stack.prompt_registry().release_promoted(
            stack.prompt_registry().get("prompt", INTENT_PROMPT_NAME, "v1"), promotion_id="x"
        )  # type: ignore[arg-type]


# ---- pinned corpus evaluation (thresholds are PROPOSED, not approved) ----


def test_the_rollout_corpus_meets_its_proposed_thresholds_and_stays_unapproved(rollout_report):
    from reference_stack import rollout_eval

    report = rollout_report
    failed = [(c["case_id"], c["detail"]) for c in report["cases"] if not c["passed"]]
    assert not failed, failed
    unmet = {name: gate for name, gate in report["gates"].items() if not gate["meets"]}
    assert report["meets_thresholds"] and not unmet and len(report["cases"]) == 12, unmet
    assert report["approval"]["status"] == "proposed" and report["approval"]["approved_by"] is None
    markdown = rollout_eval.render_markdown(report)
    assert "PROPOSED and NOT APPROVED" in markdown and "repository's policy remains proposed" in markdown


def test_the_rollout_evaluation_detects_a_wrong_expectation_and_a_changed_corpus(tmp_path, monkeypatch, rollout_report):
    """No corpus re-run: the expectation change is scored against the shared run's outcomes, and the digest lock is exercised directly."""
    import json

    from conftest import agreement_with
    from reference_stack import rollout_eval

    suite, thresholds = rollout_eval.load_suite()
    k07 = next(c for c in rollout_report["cases"] if c["case_id"] == "K07")
    assert k07["got"] != "promoted:v2" and k07["passed"]  # the controller rolled the shadow disagreement back
    assert (
        agreement_with(rollout_report, "K07", "promoted:v2") < 1.0
    )  # claiming it promotes would fail the agreement gate
    assert rollout_report["gates"]["release_immutability"]["meets"]  # the controller itself still held
    bad = json.loads(json.dumps(suite))
    next(c for c in bad["cases"] if c["id"] == "K07")["expect"] = "promoted:v2"
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(bad))
    forged = tmp_path / "thresholds.json"
    forged.write_text(json.dumps({**thresholds, "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest()}))
    monkeypatch.setattr(rollout_eval, "CORPUS", corpus)
    monkeypatch.setattr(rollout_eval, "THRESHOLDS", forged)
    loaded, _ = rollout_eval.load_suite()  # a re-pinned corpus loads, carrying the wrong expectation
    assert next(c for c in loaded["cases"] if c["id"] == "K07")["expect"] == "promoted:v2"
    forged.write_text(json.dumps(thresholds))
    with pytest.raises(rollout_eval.RolloutSuiteLockError):
        rollout_eval.load_suite()
