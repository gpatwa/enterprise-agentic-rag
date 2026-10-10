import pytest
from pydantic import ValidationError

from app.ranking.objectives import (
    MultiObjectiveUtility,
    ObjectiveName,
    ObjectiveSpec,
    UtilityPolicy,
    UtilitySignals,
)


def signals(candidate_id: str, **values: float) -> UtilitySignals:
    return UtilitySignals(candidate_id=candidate_id, signals=values)


def test_default_policy_is_deterministic_and_exposes_components() -> None:
    policy = MultiObjectiveUtility()
    candidates = (
        signals("b", qualified_play=0.8, satisfaction=0.8),
        signals("a", qualified_play=0.8, satisfaction=0.8),
    )

    result = policy.rank(candidates)

    assert [item.candidate_id for item in result] == ["a", "b"]
    assert result[0].components["qualified_play"] == 0.24
    assert "utility_policy" in result[0].evidence


def test_negative_and_safety_penalties_are_bounded() -> None:
    result = MultiObjectiveUtility().score(
        UtilitySignals(
            candidate_id="item",
            signals={"qualified_play": 1, "negative_feedback": 1},
            safety_risk=1,
        )
    )

    assert result is not None
    assert 0 <= result.score <= 1
    assert result.components["negative_feedback"] == -0.1
    assert result.components["safety_penalty"] == -0.25


def test_policy_rejects_duplicate_objectives_and_unknown_signal_names() -> None:
    with pytest.raises(ValidationError):
        UtilityPolicy(objectives=(
            ObjectiveSpec(name=ObjectiveName.SAVE, weight=0.5),
            ObjectiveSpec(name=ObjectiveName.SAVE, weight=0.5),
        ))
    with pytest.raises(ValidationError):
        UtilitySignals(candidate_id="item", signals={"not-allowed": 0.5})


def test_ineligible_candidates_never_reappear_and_kill_switch_falls_back() -> None:
    policy = UtilityPolicy(kill_switch=True)
    result = MultiObjectiveUtility(policy).rank(
        (UtilitySignals(candidate_id="blocked", eligible=False), signals("kept", qualified_play=1))
    )

    assert [item.candidate_id for item in result] == ["kept"]
    assert result[0].fallback is True
    assert result[0].score == 0
