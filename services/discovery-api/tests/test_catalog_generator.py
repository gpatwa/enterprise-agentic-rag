from __future__ import annotations

import hashlib
import json

from app.domain.models import Availability, SafetyState
from app.generation.catalog import CatalogProfile, generate_catalog, profile_spec


def test_same_seed_is_byte_identical_and_checksum_matches_records():
    first = generate_catalog(17, CatalogProfile.DEMO)
    second = generate_catalog(17, CatalogProfile.DEMO)

    assert first.canonical_records() == second.canonical_records()
    assert first.manifest.model_dump(mode="json") == second.manifest.model_dump(mode="json")
    canonical = json.dumps(
        first.canonical_records(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()
    assert first.manifest.records_checksum == hashlib.sha256(canonical).hexdigest()


def test_different_seed_changes_content():
    assert generate_catalog(17).canonical_records() != generate_catalog(18).canonical_records()


def test_profiles_are_bounded_and_cover_policy_dimensions():
    demo = generate_catalog(3, "demo")
    scale = generate_catalog(3, "scale")
    assert len(demo.experiences) == profile_spec("demo").experience_count
    assert len(demo.users) == profile_spec("demo").user_count
    assert len(scale.experiences) == profile_spec("scale").experience_count
    assert len(scale.users) == profile_spec("scale").user_count
    assert set(demo.manifest.distributions["experience_age_rating"]) == {"E", "E10", "T"}
    assert set(demo.manifest.distributions["experience_locale"]) == {"de-DE", "en-US", "es-ES", "fr-FR"}
    assert set(demo.manifest.distributions["experience_device"]) == {"desktop", "mobile", "tablet"}
    assert {item.safety_state for item in demo.experiences} == {SafetyState.APPROVED, SafetyState.RESTRICTED}
    assert {item.availability for item in demo.experiences} == {Availability.AVAILABLE, Availability.UNAVAILABLE}


def test_records_are_valid_synthetic_domain_objects_without_pii():
    dataset = generate_catalog(99)
    assert all(item.synthetic and item.provenance == "synthetic" for item in dataset.experiences)
    assert all(item.synthetic for item in dataset.users)
    assert all("@" not in item.title and "@" not in item.description for item in dataset.experiences)
    assert [item.experience_id for item in dataset.experiences] == sorted(
        item.experience_id for item in dataset.experiences
    )
    assert [item.user_id for item in dataset.users] == sorted(item.user_id for item in dataset.users)
