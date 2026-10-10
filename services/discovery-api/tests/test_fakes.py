"""Contract tests for deterministic discovery fakes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes.discovery import (
    FakeCandidate,
    FakeCandidateSource,
    FakeConfig,
    FakeDiscoveryRepository,
    FakeFeature,
    FakeFeatureProvider,
    FakeMode,
    FakeProviderError,
    FakeRanker,
    FakeTimeoutError,
)

from app.domain.models import (
    AgeRating,
    CatalogDevice,
    ConsentState,
    ExperienceRecord,
    ImmersiveDiscoveryContext,
    UserProfile,
)
from packages.platform_contracts.discovery import DiscoveryRequestContext

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "golden"


def _experiences() -> tuple[ExperienceRecord, ...]:
    records = json.loads((FIXTURE_DIR / "experiences.json").read_text())
    return tuple(ExperienceRecord.model_validate(record) for record in records[:6])


def _user(tenant_id: str = "tenant-orbit") -> UserProfile:
    return UserProfile(
        user_id="user-001",
        tenant_id=tenant_id,
        persona="short-history",
        locale="en-US",
        age_rating_limit=AgeRating.E10,
        devices=(CatalogDevice.DESKTOP,),
        history_length="short",
        preferences={"genres": ("adventure",), "themes": ("forest",)},
        consent_state=ConsentState.PERSONALIZATION_ALLOWED,
        synthetic=True,
    )


def _context(tenant_id: str = "tenant-orbit", request_id: str = "request-001") -> ImmersiveDiscoveryContext:
    return ImmersiveDiscoveryContext(
        request_context=DiscoveryRequestContext(
            tenant_id=tenant_id,
            principal_id="user-001",
            request_id=request_id,
            purpose="recommendation",
            locale="en-US",
            device="web",
        ),
        surface="recommendation",
    )


def test_fakes_are_repeatable_and_preserve_eligibility() -> None:
    experiences = _experiences()
    source = FakeCandidateSource(experiences, _user())
    context = _context()

    first = source.retrieve(context, limit=10)
    second = source.retrieve(context, limit=10)

    assert first == second
    assert [candidate.experience_id for candidate in first] == [
        "exp-001",
        "exp-002",
        "exp-004",
        "exp-005",
    ]
    assert len(source.trace) == 2
    assert source.trace[0].tenant_digest != "tenant-orbit"


def test_repository_and_profile_are_tenant_scoped() -> None:
    experiences = _experiences()
    repository = FakeDiscoveryRepository(experiences, (_user(), _user("tenant-lumen")))

    assert len(repository.read_catalog(_context())) == 6
    assert repository.read_catalog(_context("tenant-lumen")) == ()
    assert repository.read_profile(_context()).user_id == "user-001"
    assert repository.read_profile(_context("tenant-lumen")) is not None


def test_feature_and_ranker_outputs_are_deterministic() -> None:
    context = _context()
    candidates = (
        {"experience_id": "exp-002", "source": "fake", "score": 0.4},
        {"experience_id": "exp-001", "source": "fake", "score": 0.4},
    )
    candidates = tuple(FakeCandidate(**item) for item in candidates)
    features = FakeFeatureProvider(
        (FakeFeature(experience_id="exp-001", values=(("quality", 1.0),)),)
    )
    hydrated = features.hydrate(context, candidates)
    ranked = FakeRanker().rank(context, candidates, hydrated)

    assert [item.experience_id for item in ranked] == ["exp-001", "exp-002"]
    assert ranked == FakeRanker().rank(context, candidates, hydrated)


@pytest.mark.parametrize("mode, error", [(FakeMode.FAILURE, FakeProviderError), (FakeMode.TIMEOUT, FakeTimeoutError)])
def test_failure_and_timeout_modes_are_explicit(mode: FakeMode, error: type[Exception]) -> None:
    source = FakeCandidateSource(_experiences(), _user(), FakeConfig(mode=mode))

    with pytest.raises(error, match="fake retrieve"):
        source.retrieve(_context())
    assert len(source.trace) == 1


def test_call_and_item_bounds_are_enforced() -> None:
    context = _context()
    source = FakeCandidateSource(_experiences(), _user(), FakeConfig(max_calls=1, max_items=10))

    source.retrieve(context, limit=10)
    with pytest.raises(FakeProviderError, match="call limit"):
        source.retrieve(context, limit=10)
    with pytest.raises(ValueError, match="limit"):
        FakeCandidateSource(_experiences(), _user(), FakeConfig(max_items=2)).retrieve(context, limit=3)
