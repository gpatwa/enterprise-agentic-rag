import json
from pathlib import Path

import pytest

from app.candidates.similar import ItemSimilarityCandidateSource, SimilarityVector
from app.domain.models import ExperienceRecord, ImmersiveDiscoveryContext, UserProfile
from packages.platform_contracts.discovery import DiscoveryRequestContext

FIXTURE = Path(__file__).parent / "fixtures" / "golden" / "experiences.json"


def _experience(index=0, **overrides):
    values = json.loads(FIXTURE.read_text())[index]
    values.update(overrides)
    return ExperienceRecord.model_validate(values)


def _context(**overrides):
    values = dict(tenant_id="tenant-orbit", principal_id="user-001", request_id="request-001", purpose="related", locale="en-US", device="web", age=16)
    values.update(overrides)
    return ImmersiveDiscoveryContext(request_context=DiscoveryRequestContext(**values), surface="related", seed_experience_id="exp-001")


def _user(**overrides):
    values = dict(user_id="user-001", tenant_id="tenant-orbit", persona="item-neighbor", locale="en-US", age_rating_limit="T", devices=("desktop",), history_length="short", preferences={"genres": (), "themes": ()}, consent_state="personalization_allowed", synthetic=True)
    values.update(overrides)
    return UserProfile.model_validate(values)


def test_metadata_similarity_is_deterministic_and_excludes_seed():
    experiences = (_experience(0), _experience(17), _experience(2))
    source = ItemSimilarityCandidateSource()
    first = source.retrieve(experiences[0], experiences, _context(), _user())
    second = source.retrieve(experiences[0], tuple(reversed(experiences)), _context(), _user())
    assert first.model_dump() == second.model_dump()
    assert all(item.experience_id != "exp-001" for item in first.source_result.candidates)
    assert first.source_result.candidates[0].reason_codes == ("metadata_overlap",)


def test_vector_similarity_requires_one_version_and_blends_with_metadata():
    experiences = (_experience(0), _experience(17), _experience(2))
    vectors = (
        SimilarityVector(experience_id="exp-001", values=(1.0, 0.0), model_version="embed-v1", dimensions=2),
        SimilarityVector(experience_id="exp-018", values=(1.0, 0.0), model_version="embed-v1", dimensions=2),
    )
    result = ItemSimilarityCandidateSource().retrieve(experiences[0], experiences, _context(), _user(), vectors=vectors)
    assert result.source_result.candidates[0].experience_id == "exp-018"
    assert result.evidence[0].vector_score == 1.0
    assert result.source_result.candidates[0].reason_codes == ("metadata_overlap", "vector_cosine")
    with pytest.raises(ValueError, match="mixed vector versions"):
        ItemSimilarityCandidateSource().retrieve(
            experiences[0], experiences, _context(), _user(),
            vectors=(*vectors, SimilarityVector(experience_id="exp-003", values=(0.0, 1.0), model_version="embed-v2", dimensions=2)),
        )


def test_hard_eligibility_and_tenant_boundaries_apply_before_scoring():
    experiences = (
        _experience(0),
        _experience(17),
        _experience(2, tenant_id="tenant-other"),
        _experience(17, experience_id="exp-018-restricted", safety_state="restricted"),
    )
    result = ItemSimilarityCandidateSource().retrieve(experiences[0], experiences, _context(), _user())
    assert {item.experience_id for item in result.source_result.candidates} == {"exp-018"}


def test_blocked_items_are_excluded_before_scoring():
    seed, related = _experience(0), _experience(17)
    result = ItemSimilarityCandidateSource().retrieve(seed, (seed, related), _context(), _user(), blocked_ids=(related.experience_id,))
    assert result.source_result.candidates == ()


def test_no_overlap_returns_explicit_empty_result():
    seed = _experience(0)
    unrelated = _experience(1, genres=("sports",), themes=("snow",), mechanics=("racing",))
    result = ItemSimilarityCandidateSource().retrieve(seed, (seed, unrelated), _context(), _user())
    assert result.source_result.candidates == ()
    assert result.source_result.degradation.value == "empty"
