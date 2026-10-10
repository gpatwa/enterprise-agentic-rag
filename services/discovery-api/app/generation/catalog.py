"""Seedable, local-only catalog and persona generation.

The generator intentionally creates only fictional records.  IDs are ordinal
and names come from a small vocabulary so a seed changes the catalog content,
not its reproducibility or its privacy properties.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import (
    AgeRating,
    Availability,
    CatalogDevice,
    ConsentState,
    ExperienceRecord,
    ExperienceSignals,
    ExplicitPreferences,
    FreshnessBand,
    Genre,
    HistoryLength,
    Locale,
    Mechanic,
    Persona,
    PopularityBand,
    QualityBand,
    SafetyState,
    Theme,
    UserProfile,
)


class CatalogProfile(str, Enum):
    DEMO = "demo"
    SCALE = "scale"


@dataclass(frozen=True)
class CatalogProfileSpec:
    """Bounded generation sizes and coverage targets for one profile."""

    profile: CatalogProfile
    experience_count: int
    user_count: int
    creator_count: int
    tenant_count: int


_PROFILE_SPECS = {
    CatalogProfile.DEMO: CatalogProfileSpec(CatalogProfile.DEMO, 48, 24, 12, 2),
    CatalogProfile.SCALE: CatalogProfileSpec(CatalogProfile.SCALE, 240, 120, 24, 4),
}


class CatalogManifest(BaseModel):
    """Integrity and coverage metadata for a generated dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int
    profile: CatalogProfile
    counts: dict[str, int]
    distributions: dict[str, dict[str, int]]
    records_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CatalogDataset:
    """The complete deterministic output of :func:`generate_catalog`."""

    experiences: tuple[ExperienceRecord, ...]
    users: tuple[UserProfile, ...]
    manifest: CatalogManifest

    def canonical_records(self) -> list[dict[str, Any]]:
        """Return records in the exact order used by the manifest checksum."""
        return [
            {"kind": "experience", "record": record.model_dump(mode="json")}
            for record in self.experiences
        ] + [
            {"kind": "user", "record": record.model_dump(mode="json")}
            for record in self.users
        ]


T = TypeVar("T")
_TITLE_ADJECTIVES = ("Amber", "Bright", "Cloud", "Crystal", "Moss", "Neon", "Quiet", "Silver")
_TITLE_NOUNS = ("Harbor", "Garden", "Relay", "Vale", "Workshop", "Orchard", "Station", "Trail")
_DESCRIPTION_TEMPLATES = (
    "Explore a fictional {theme} world through {mechanic} challenges.",
    "Build a friendly {theme} space and discover {mechanic} adventures.",
    "Practice {mechanic} skills in a colorful {theme} setting.",
)
_ALL_GENRES = tuple(Genre)
_ALL_THEMES = tuple(Theme)
_ALL_MECHANICS = tuple(Mechanic)
_ALL_DEVICES = tuple(CatalogDevice)
_ALL_LOCALES = tuple(Locale)
_ALL_PERSONAS = tuple(Persona)
_ALL_AGE_RATINGS = tuple(AgeRating)


def profile_spec(profile: CatalogProfile | str) -> CatalogProfileSpec:
    """Resolve a named profile while keeping generation sizes bounded."""
    resolved = profile if isinstance(profile, CatalogProfile) else CatalogProfile(profile)
    return _PROFILE_SPECS[resolved]


def generate_catalog(seed: int, profile: CatalogProfile | str = CatalogProfile.DEMO) -> CatalogDataset:
    """Generate valid, fictional catalog and user records from ``seed``."""
    spec = profile_spec(profile)
    rng = random.Random(seed)
    experiences = _generate_experiences(rng, spec)
    users = _generate_users(rng, spec)
    records = [
        {"kind": "experience", "record": record.model_dump(mode="json")}
        for record in experiences
    ] + [{"kind": "user", "record": record.model_dump(mode="json")} for record in users]
    distributions = _distributions(experiences, users)
    manifest = CatalogManifest(
        seed=seed,
        profile=spec.profile,
        counts={"experiences": len(experiences), "users": len(users)},
        distributions=distributions,
        records_checksum=_checksum(records),
    )
    return CatalogDataset(tuple(experiences), tuple(users), manifest)


def _generate_experiences(rng: random.Random, spec: CatalogProfileSpec) -> list[ExperienceRecord]:
    records: list[ExperienceRecord] = []
    for index in range(spec.experience_count):
        tenant_index = index % spec.tenant_count
        creator_index = index % spec.creator_count
        theme = _ALL_THEMES[rng.randrange(len(_ALL_THEMES))]
        mechanic = _ALL_MECHANICS[rng.randrange(len(_ALL_MECHANICS))]
        records.append(
            ExperienceRecord(
                experience_id=f"exp-{index + 1:04d}",
                creator_id=f"creator-{creator_index + 1:03d}",
                tenant_id=f"tenant-{tenant_index + 1:02d}",
                title=f"{_TITLE_ADJECTIVES[rng.randrange(len(_TITLE_ADJECTIVES))]} "
                f"{_TITLE_NOUNS[rng.randrange(len(_TITLE_NOUNS))]} {index + 1:03d}",
                description=_DESCRIPTION_TEMPLATES[rng.randrange(len(_DESCRIPTION_TEMPLATES))].format(
                    theme=theme.value, mechanic=mechanic.value
                ),
                genres=_pick_many(rng, _ALL_GENRES, 1, 3),
                themes=(theme, *_pick_many(rng, tuple(item for item in _ALL_THEMES if item != theme), 0, 1)),
                mechanics=(mechanic, *_pick_many(rng, tuple(item for item in _ALL_MECHANICS if item != mechanic), 0, 1)),
                devices=_coverage_pick(rng, _ALL_DEVICES, index, 1, 3),
                locales=_coverage_pick(rng, _ALL_LOCALES, index, 1, 4),
                age_rating=_ALL_AGE_RATINGS[index % len(_ALL_AGE_RATINGS)],
                safety_state=SafetyState.RESTRICTED if index % 17 == 0 else SafetyState.APPROVED,
                availability=Availability.UNAVAILABLE if index % 19 == 0 else Availability.AVAILABLE,
                synthetic=True,
                signals=ExperienceSignals(
                    freshness_band=tuple(FreshnessBand)[index % len(FreshnessBand)],
                    quality_band=tuple(QualityBand)[index % len(QualityBand)],
                    popularity_band=tuple(PopularityBand)[index % len(PopularityBand)],
                ),
            )
        )
    return records


def _generate_users(rng: random.Random, spec: CatalogProfileSpec) -> list[UserProfile]:
    records: list[UserProfile] = []
    for index in range(spec.user_count):
        persona = _ALL_PERSONAS[index % len(_ALL_PERSONAS)]
        preference_genres = _pick_many(rng, _ALL_GENRES, 0 if persona in {Persona.COLD_START, Persona.GUEST} else 1, 2)
        preference_themes = _pick_many(rng, _ALL_THEMES, 0 if persona in {Persona.COLD_START, Persona.GUEST} else 1, 2)
        records.append(
            UserProfile(
                user_id=f"user-{index + 1:04d}",
                tenant_id=f"tenant-{index % spec.tenant_count + 1:02d}",
                persona=persona,
                locale=_ALL_LOCALES[index % len(_ALL_LOCALES)],
                age_rating_limit=_ALL_AGE_RATINGS[index % len(_ALL_AGE_RATINGS)],
                devices=_coverage_pick(rng, _ALL_DEVICES, index, 1, 3),
                history_length=tuple(HistoryLength)[index % len(HistoryLength)],
                preferences=ExplicitPreferences(genres=preference_genres, themes=preference_themes),
                consent_state=(
                    ConsentState.PERSONALIZATION_DENIED
                    if index % 8 == 0
                    else ConsentState.PERSONALIZATION_ALLOWED
                ),
                synthetic=True,
            )
        )
    return records


def _pick_many(rng: random.Random, values: Sequence[T], minimum: int, maximum: int) -> tuple[T, ...]:
    count = rng.randint(minimum, maximum)
    return tuple(sorted(rng.sample(list(values), count), key=lambda item: item.value))


def _coverage_pick(
    rng: random.Random, values: Sequence[T], index: int, minimum: int, maximum: int
) -> tuple[T, ...]:
    count = max(minimum, min(maximum, 1 + rng.randrange(maximum)))
    selected = [values[index % len(values)]]
    remaining = [value for value in values if value not in selected]
    selected.extend(rng.sample(remaining, min(count - 1, len(remaining))))
    return tuple(sorted(selected, key=lambda item: item.value))


def _distributions(
    experiences: Sequence[ExperienceRecord], users: Sequence[UserProfile]
) -> dict[str, dict[str, int]]:
    return {
        "experience_age_rating": _count(experiences, lambda item: item.age_rating.value),
        "experience_locale": _count_many(experiences, lambda item: item.locales),
        "experience_device": _count_many(experiences, lambda item: item.devices),
        "experience_safety": _count(experiences, lambda item: item.safety_state.value),
        "user_persona": _count(users, lambda item: item.persona.value),
        "user_locale": _count(users, lambda item: item.locale.value),
        "user_consent": _count(users, lambda item: item.consent_state.value),
    }


def _count(records: Sequence[T], key) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = key(record)
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _count_many(records: Sequence[T], key) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for value in key(record):
            counts[value.value] = counts.get(value.value, 0) + 1
    return dict(sorted(counts.items()))


def _checksum(records: list[dict[str, Any]]) -> str:
    serialized = json.dumps(records, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
