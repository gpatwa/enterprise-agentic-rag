import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.candidates.trending import TrendingCandidateSource, TrendingConfig
from app.domain.models import ConsentState, ExperienceRecord, ImmersiveDiscoveryContext, UserProfile
from app.features.materialization import FeatureKind, FeatureRecord
from packages.platform_contracts.discovery import DiscoveryRequestContext

AS_OF = datetime(2026, 1, 10, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "golden"


def _context(**overrides):
    values = dict(tenant_id="tenant-orbit", principal_id="user-001", request_id="request-001", purpose="recommendation", locale="en-US", device="web", age=16)
    values.update(overrides)
    return ImmersiveDiscoveryContext(request_context=DiscoveryRequestContext(**values), surface="home")


def _user():
    return UserProfile.model_validate({"user_id": "user-001", "tenant_id": "tenant-orbit", "persona": "quality-seeker", "locale": "en-US", "age_rating_limit": "T", "devices": ["desktop"], "history_length": "short", "preferences": {"genres": [], "themes": []}, "consent_state": "personalization_allowed", "synthetic": True})


def _experience(index=0, **overrides):
    values = json.loads((FIXTURE / "experiences.json").read_text())[index]
    values.update(overrides)
    return ExperienceRecord.model_validate(values)


def _feature(experience_id, *, as_of=AS_OF, impressions=100.0, qualified_plays=50.0, age=0.0, version="v1"):
    return FeatureRecord(tenant_id="tenant-orbit", subject_type=FeatureKind.POPULARITY, subject_id=experience_id, feature_version=version, as_of=as_of, source_watermark=as_of, feature_age_seconds=age, consent_state=ConsentState.PERSONALIZATION_ALLOWED, synthetic=True, values={"impressions": impressions, "qualified_plays": qualified_plays, "qualified_play_rate": qualified_plays / impressions if impressions else 0.0})


def test_trending_is_deterministic_and_emits_stable_evidence():
    experiences = (_experience(0), _experience(1))
    features = (_feature("exp-001", qualified_plays=80.0), _feature("exp-002", qualified_plays=20.0))
    source = TrendingCandidateSource()
    first = source.retrieve(features, experiences, _context(), _user(), as_of=AS_OF)
    second = source.retrieve(tuple(reversed(features)), tuple(reversed(experiences)), _context(), _user(), as_of=AS_OF)
    assert first.model_dump() == second.model_dump()
    assert first.source_result.candidates[0].experience_id == "exp-001"
    assert "time_decay" in first.evidence[0].reason_codes


def test_small_items_are_normalized_and_stale_features_are_rejected():
    source = TrendingCandidateSource(TrendingConfig(max_feature_age_seconds=3600.0))
    result = source.retrieve((_feature("exp-001", impressions=1.0, qualified_plays=1.0),), (_experience(0),), _context(), _user(), as_of=AS_OF)
    assert result.evidence[0].popularity_score < 1.0
    assert result.source_result.candidates[0].score < 1.0
    with pytest.raises(ValueError, match="stale"):
        source.retrieve((_feature("exp-001", age=3601.0),), (_experience(0),), _context(), _user(), as_of=AS_OF)


def test_hard_eligibility_and_tenant_boundaries_apply_before_scoring():
    experiences = (_experience(0), _experience(1, tenant_id="tenant-other"), _experience(2, safety_state="restricted"))
    features = (_feature("exp-001"), _feature("exp-002"), _feature("exp-003"))
    result = TrendingCandidateSource().retrieve(features, experiences, _context(), _user(), as_of=AS_OF)
    assert [item.experience_id for item in result.source_result.candidates] == ["exp-001"]


def test_future_or_mismatched_features_fail_closed():
    with pytest.raises(ValueError, match="after"):
        TrendingCandidateSource().retrieve((_feature("exp-001", as_of=AS_OF + timedelta(seconds=1)),), (_experience(0),), _context(), _user(), as_of=AS_OF)
    with pytest.raises(ValueError, match="version"):
        TrendingCandidateSource().retrieve((_feature("exp-001", version="v2"),), (_experience(0),), _context(), _user(), as_of=AS_OF)
