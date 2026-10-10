from app.domain.models import AgeRating, Availability, ConsentState, SafetyState
from app.ranking.exploration import (
    ExplorationCandidate,
    ExplorationPolicy,
    ExplorationPolicyRunner,
    ExplorationRequest,
)


def candidate(candidate_id: str, **overrides: object) -> ExplorationCandidate:
    values: dict[str, object] = {
        "candidate_id": candidate_id,
        "tenant_id": "tenant-a",
        "creator_id": f"creator-{candidate_id}",
        "quality_score": 0.9,
        "age_rating": AgeRating.E,
        "safety_state": SafetyState.APPROVED,
        "availability": Availability.AVAILABLE,
    }
    values.update(overrides)
    return ExplorationCandidate(**values)


def request(*candidates: ExplorationCandidate, **overrides: object) -> ExplorationRequest:
    values: dict[str, object] = {
        "request_id": "request-1",
        "user_id": "user-1",
        "tenant_id": "tenant-a",
        "age_rating_limit": AgeRating.E10,
        "consent_state": ConsentState.PERSONALIZATION_ALLOWED,
        "candidates": tuple(candidates),
    }
    values.update(overrides)
    return ExplorationRequest(**values)


def test_selection_is_seeded_and_bounded() -> None:
    items = tuple(candidate(f"item-{index}") for index in range(5))
    policy = ExplorationPolicy(seed="seed-a", per_request_budget=2, max_per_creator=5)
    runner = ExplorationPolicyRunner(policy)

    first = runner.select(request(*items))
    second = runner.select(request(*items))

    assert tuple(item.candidate_id for item in first.candidates) == tuple(item.candidate_id for item in second.candidates)
    assert len(first.candidates) == 2
    assert first.fallback is False


def test_hard_policy_filters_run_before_selection() -> None:
    result = ExplorationPolicyRunner(ExplorationPolicy(max_per_creator=5)).select(
        request(
            candidate("wrong-tenant", tenant_id="tenant-b"),
            candidate("unsafe", safety_state=SafetyState.RESTRICTED),
            candidate("unavailable", availability=Availability.UNAVAILABLE),
            candidate("too-old", age_rating=AgeRating.T),
            candidate("low-quality", quality_score=0.1),
            candidate("blocked", blocked=True),
            candidate("allowed"),
        )
    )

    assert tuple(item.candidate_id for item in result.candidates) == ("allowed",)
    assert all(not item.selected for item in result.evidence if item.candidate_id != "allowed")


def test_consent_and_candidate_exposure_are_enforced() -> None:
    result = ExplorationPolicyRunner(ExplorationPolicy(max_per_creator=5)).select(
        request(
            candidate("personalized", personalization_required=True),
            candidate("seen", prior_exposures=1),
            candidate("allowed"),
            consent_state=ConsentState.PERSONALIZATION_DENIED,
        )
    )

    assert tuple(item.candidate_id for item in result.candidates) == ("allowed",)
    reasons = {reason for item in result.evidence for reason in item.reason_codes}
    assert {"consent", "candidate_exposure_cap"} <= reasons


def test_creator_cap_bounds_exploration_exposure() -> None:
    result = ExplorationPolicyRunner(ExplorationPolicy(per_request_budget=3, max_per_creator=1)).select(
        request(
            candidate("a-1", creator_id="creator-a"),
            candidate("a-2", creator_id="creator-a"),
            candidate("b-1", creator_id="creator-b"),
        )
    )

    assert len(result.candidates) == 2
    assert {item.creator_id for item in result.candidates} == {"creator-a", "creator-b"}


def test_user_budget_exhaustion_is_a_deterministic_fallback() -> None:
    result = ExplorationPolicyRunner(ExplorationPolicy(per_user_budget=2)).select(
        request(candidate("item"), user_exposures=2)
    )

    assert result.candidates == ()
    assert result.fallback is True
    assert result.reason_codes == ("budget_exhausted",)


def test_kill_switch_never_selects_candidates() -> None:
    result = ExplorationPolicyRunner(ExplorationPolicy(enabled=False)).select(request(candidate("item")))

    assert result.candidates == ()
    assert result.fallback is True
    assert result.reason_codes == ("kill_switch",)
