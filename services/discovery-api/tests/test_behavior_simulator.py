from datetime import datetime, timezone

import pytest

from app.domain.models import ImmersiveDiscoveryContext
from app.generation.catalog import generate_catalog
from app.simulation.behavior import BehaviorSimulator, SimulationProfile, simulate_behavior
from packages.platform_contracts.discovery import DiscoveryRequestContext


def _run(seed: int = 7):
    dataset = generate_catalog(seed=31, profile="demo")
    user = dataset.users[1]
    context = ImmersiveDiscoveryContext(
        request_context=DiscoveryRequestContext(
            tenant_id=user.tenant_id,
            principal_id=user.user_id,
            request_id="request-sim-001",
            purpose="recommendation",
            locale=user.locale.value,
            device="web",
        ),
        surface="recommendation",
    )
    return simulate_behavior(seed, user, dataset.experiences, context)


def test_same_seed_is_identical_and_events_are_bounded_and_ordered() -> None:
    first = _run()
    second = _run()

    assert first.batch.serialize() == second.batch.serialize()
    assert len(first.events) <= 64
    assert len(first.exposed_experience_ids) <= 8
    assert list(first.events) == sorted(first.events, key=lambda item: (item.occurred_at, item.event_id))
    assert all(item.synthetic for item in first.events)


def test_actions_have_matching_impression_lineage_and_expected_signals() -> None:
    result = _run()
    impressions = {item.experience_id: item for item in result.events if item.event_type.value == "impression"}
    actions = [item for item in result.events if item.event_type.value != "impression"]

    assert actions
    assert {item.event_type.value for item in actions} >= {"click", "play", "playtime", "retention"}
    for action in actions:
        assert action.impression_token == impressions[action.experience_id].impression_token
        assert action.tenant_id == action.impression_token.tenant_id
        assert action.user_id == action.impression_token.principal_id
        assert action.request_id == action.impression_token.request_id


def test_profile_and_persona_rules_produce_social_and_qualified_events() -> None:
    dataset = generate_catalog(seed=31, profile="demo")
    user = next(item for item in dataset.users if item.persona.value == "social")
    context = ImmersiveDiscoveryContext(
        request_context=DiscoveryRequestContext(
            tenant_id=user.tenant_id,
            principal_id=user.user_id,
            request_id="request-social-001",
            purpose="home",
            locale=user.locale.value,
            device="web",
        ),
        surface="home",
    )
    result = BehaviorSimulator(3, profile=SimulationProfile.EVALUATION).simulate(user, dataset.experiences, context)
    types = {item.event_type.value for item in result.events}
    assert "co_play" in types
    assert "qualified_play" in types


def test_only_prior_exposed_state_is_used_and_real_records_are_rejected() -> None:
    dataset = generate_catalog(seed=31, profile="demo")
    user = dataset.users[0]
    context = ImmersiveDiscoveryContext(
        request_context=DiscoveryRequestContext(
            tenant_id=user.tenant_id,
            principal_id=user.user_id,
            request_id="request-sim-002",
            purpose="search",
            locale=user.locale.value,
            device="web",
        ),
        surface="search",
    )
    result = BehaviorSimulator(4).simulate(user, dataset.experiences, context)
    assert all(item.occurred_at >= datetime(2026, 1, 1, tzinfo=timezone.utc) for item in result.events)
    with pytest.raises(ValueError, match="synthetic"):
        BehaviorSimulator(4).simulate(user.model_copy(update={"synthetic": False}), dataset.experiences, context)
