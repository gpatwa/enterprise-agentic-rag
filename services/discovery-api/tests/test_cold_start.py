import json
from pathlib import Path

import pytest

from app.candidates.cold_start import ColdStartCandidateSource, ColdStartConfig
from app.domain.models import ExperienceRecord, HistoryLength, ImmersiveDiscoveryContext, UserProfile
from packages.platform_contracts.discovery import DiscoveryRequestContext

FIXTURE = Path(__file__).parent / "fixtures" / "golden" / "experiences.json"


def _experience(index=0, **overrides):
    values = json.loads(FIXTURE.read_text())[index]
    values.update(overrides)
    if overrides.get("signals", object()) is None:
        for name in ("freshness_band", "quality_band", "popularity_band"):
            values.pop(name, None)
    return ExperienceRecord.model_validate(values)


def _context(**overrides):
    values = dict(tenant_id="tenant-orbit", principal_id="user-001", request_id="request-001", purpose="recommendation", locale="en-US", device="web", age=16)
    values.update(overrides)
    return ImmersiveDiscoveryContext(request_context=DiscoveryRequestContext(**values), surface="home")


def _user(**overrides):
    values = dict(user_id="user-001", tenant_id="tenant-orbit", persona="cold-start", locale="en-US", age_rating_limit="T", devices=("desktop",), history_length="none", preferences={"genres": (), "themes": ()}, consent_state="personalization_allowed", synthetic=True)
    values.update(overrides)
    return UserProfile.model_validate(values)


def test_new_user_is_deterministic_and_emits_cold_start_reasons():
    experiences = tuple(_experience(index) for index in range(4))
    source = ColdStartCandidateSource()
    first = source.retrieve(experiences, _context(), _user(), seed="seed-1")
    second = source.retrieve(tuple(reversed(experiences)), _context(), _user(), seed="seed-1")
    assert first.model_dump() == second.model_dump()
    assert first.evidence[0].cold_start_state == "new_user"
    assert "bounded_exploration" in first.evidence[0].reason_codes


def test_new_items_are_selected_for_existing_users_and_known_items_are_excluded():
    existing = _experience(0)
    new_item = _experience(1, signals=None)
    user = _user(history_length=HistoryLength.SHORT)
    result = ColdStartCandidateSource().retrieve((existing, new_item), _context(), user, item_history={"exp-001": 10})
    assert [item.experience_id for item in result.source_result.candidates] == ["exp-002"]
    assert result.evidence[0].cold_start_state == "new_item"


def test_safety_tenant_and_quality_filters_apply_before_exploration():
    experiences = (
        _experience(0),
        _experience(1, safety_state="restricted"),
        _experience(2, tenant_id="tenant-other"),
        _experience(3, availability="unavailable"),
    )
    result = ColdStartCandidateSource().retrieve(experiences, _context(), _user())
    assert [item.experience_id for item in result.source_result.candidates] == ["exp-001"]


def test_creator_and_exploration_caps_are_bounded():
    experiences = tuple(_experience(index, experience_id=f"item-{index}") for index in range(4))
    result = ColdStartCandidateSource(ColdStartConfig(max_candidates=4, max_exploration_candidates=2, max_per_creator=1)).retrieve(experiences, _context(), _user())
    assert len(result.source_result.candidates) == 1
    assert len(result.source_result.candidates) <= 2


def test_invalid_item_history_fails_closed():
    with pytest.raises(ValueError, match="non-negative integers"):
        ColdStartCandidateSource().retrieve((_experience(0),), _context(), _user(), item_history={"exp-001": -1})
