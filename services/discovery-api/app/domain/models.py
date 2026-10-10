"""Immutable domain contracts for immersive discovery."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.platform_contracts.discovery import DiscoveryRequestContext


class _DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgeRating(str, Enum):
    E = "E"
    E10 = "E10"
    T = "T"


class SafetyState(str, Enum):
    APPROVED = "approved"
    RESTRICTED = "restricted"


class Availability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class CatalogDevice(str, Enum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"


class Locale(str, Enum):
    EN_US = "en-US"
    ES_ES = "es-ES"
    FR_FR = "fr-FR"
    DE_DE = "de-DE"


class Genre(str, Enum):
    ACTION = "action"
    ADVENTURE = "adventure"
    ARCADE = "arcade"
    BUILDING = "building"
    CASUAL = "casual"
    PUZZLE = "puzzle"
    RACING = "racing"
    ROLEPLAY = "roleplay"
    SIMULATION = "simulation"
    SOCIAL = "social"
    SPORTS = "sports"
    STRATEGY = "strategy"


class Theme(str, Enum):
    ART = "art"
    CANYON = "canyon"
    CAVE = "cave"
    CITY = "city"
    COASTAL = "coastal"
    COLORFUL = "colorful"
    COZY = "cozy"
    CRYSTAL = "crystal"
    CLOCKWORK = "clockwork"
    FOOD = "food"
    FANTASY = "fantasy"
    FOREST = "forest"
    FUTURISTIC = "futuristic"
    GARDEN = "garden"
    HORROR = "horror"
    INDUSTRIAL = "industrial"
    ISLAND = "island"
    MARSH = "marsh"
    MEADOW = "meadow"
    MYSTERY = "mystery"
    NEON = "neon"
    OCEAN = "ocean"
    RIVER = "river"
    SKY = "sky"
    SNOW = "snow"
    SPACE = "space"
    TOWN = "town"
    VALLEY = "valley"
    WILDERNESS = "wilderness"
    WHIMSICAL = "whimsical"


class Mechanic(str, Enum):
    BUILDING = "building"
    COLLECTING = "collecting"
    COOPERATIVE_PUZZLE = "cooperative-puzzle"
    CO_PLAY = "co-play"
    EXPLORATION = "exploration"
    LEADERBOARD = "leaderboard"
    LOGIC = "logic"
    PLANNING = "planning"
    RACING = "racing"
    REFLEX = "reflex"
    SCORE_CHASING = "score-chasing"
    TIMING = "timing"
    TIME_TRIAL = "time-trial"
    TRADING = "trading"


class FreshnessBand(str, Enum):
    FRESH = "fresh"
    STEADY = "steady"
    STALE = "stale"


class QualityBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"


class PopularityBand(str, Enum):
    NICHE = "niche"
    RISING = "rising"
    POPULAR = "popular"


class ConsentState(str, Enum):
    PERSONALIZATION_ALLOWED = "personalization_allowed"
    PERSONALIZATION_DENIED = "personalization_denied"


class Persona(str, Enum):
    EXPLICIT_PREFERENCE = "explicit-preference"
    SHORT_HISTORY = "short-history"
    LONG_HISTORY = "long-history"
    SOCIAL = "social"
    MULTILINGUAL = "multilingual"
    DEVICE_CONSTRAINED = "device-constrained"
    COLD_START = "cold-start"
    NO_PERSONALIZATION = "no-personalization"
    TEEN_SAFE = "teen-safe"
    FRESHNESS_SEEKER = "freshness-seeker"
    QUALITY_SEEKER = "quality-seeker"
    ITEM_NEIGHBOR = "item-neighbor"
    NEW_ITEM_REVIEWER = "new-item-reviewer"
    DIVERSITY_SEEKER = "diversity-seeker"
    QUIET_PLAYER = "quiet-player"
    GUEST = "guest"


class HistoryLength(str, Enum):
    NONE = "none"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class ExperienceSignals(_DomainModel):
    """Versioned, rebuildable signals; never catalog authority."""

    freshness_band: FreshnessBand
    quality_band: QualityBand
    popularity_band: PopularityBand
    signals_version: str = Field(default="v1", min_length=1, max_length=64)
    derived_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class ExperienceRecord(_DomainModel):
    """Authoritative experience metadata with explicitly separate signals."""

    experience_id: str = Field(min_length=1, max_length=255)
    creator_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=4000)
    genres: tuple[Genre, ...] = Field(min_length=1, max_length=20)
    themes: tuple[Theme, ...] = Field(min_length=1, max_length=20)
    mechanics: tuple[Mechanic, ...] = Field(min_length=1, max_length=20)
    devices: tuple[CatalogDevice, ...] = Field(min_length=1, max_length=3)
    locales: tuple[Locale, ...] = Field(min_length=1, max_length=4)
    age_rating: AgeRating
    safety_state: SafetyState
    availability: Availability
    synthetic: bool
    provenance: Literal["synthetic", "licensed", "first_party"] = "synthetic"
    signals: ExperienceSignals | None = None

    @model_validator(mode="before")
    @classmethod
    def materialize_fixture_signals(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        signal_names = ("freshness_band", "quality_band", "popularity_band")
        present = [name for name in signal_names if name in value]
        if not present:
            return value
        if len(present) != len(signal_names):
            raise ValueError("all derived signal fields must be supplied together")
        if "signals" in value:
            raise ValueError("derived signals must be supplied either nested or flat")
        authoritative = dict(value)
        signal_values = {name: authoritative.pop(name) for name in signal_names}
        authoritative["signals"] = signal_values
        return authoritative

    @model_validator(mode="after")
    def validate_values(self) -> "ExperienceRecord":
        _require_nonblank(self.experience_id, self.creator_id, self.tenant_id, self.title, self.description)
        if self.synthetic and self.provenance != "synthetic":
            raise ValueError("synthetic records must use synthetic provenance")
        return self


class ExplicitPreferences(_DomainModel):
    genres: tuple[Genre, ...] = Field(default_factory=tuple, max_length=20)
    themes: tuple[Theme, ...] = Field(default_factory=tuple, max_length=20)


class UserProfile(_DomainModel):
    user_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    persona: Persona
    locale: Locale
    age_rating_limit: AgeRating
    devices: tuple[CatalogDevice, ...] = Field(min_length=1, max_length=3)
    history_length: HistoryLength
    preferences: ExplicitPreferences
    consent_state: ConsentState
    synthetic: bool

    @model_validator(mode="after")
    def validate_values(self) -> "UserProfile":
        _require_nonblank(self.user_id, self.tenant_id)
        return self


class ExperienceFilters(_DomainModel):
    genres: tuple[Genre, ...] = Field(default_factory=tuple, max_length=10)
    themes: tuple[Theme, ...] = Field(default_factory=tuple, max_length=10)
    devices: tuple[CatalogDevice, ...] = Field(default_factory=tuple, max_length=3)
    locales: tuple[Locale, ...] = Field(default_factory=tuple, max_length=4)


class ImmersiveDiscoveryContext(_DomainModel):
    request_context: DiscoveryRequestContext
    surface: Literal["search", "home", "recommendation", "related"]
    seed_experience_id: str | None = Field(default=None, min_length=1, max_length=255)
    filters: ExperienceFilters = Field(default_factory=ExperienceFilters)


class EligibilityReasonCode(str, Enum):
    ALLOW = "allow"
    SAFE_CATALOG_FALLBACK = "safe_catalog_fallback"
    PERSONALIZATION_CONSENT_DENIED = "personalization_consent_denied"
    MISSING_CONTEXT = "missing_context"
    TENANT_SCOPE_MISMATCH = "tenant_scope_mismatch"
    AGE_RATING_EXCEEDS_PROFILE_LIMIT = "age_rating_exceeds_profile_limit"
    SAFETY_STATE_RESTRICTED = "safety_state_restricted"
    SAFETY_BLOCK = "safety_block"
    EXPERIENCE_UNAVAILABLE = "experience_unavailable"
    LOCALE_NOT_SUPPORTED = "locale_not_supported"
    DEVICE_NOT_SUPPORTED = "device_not_supported"
    PERSONALIZATION_CONSENT_REQUIRED = "personalization_consent_required"


class EligibilityConstraints(_DomainModel):
    tenant_id: str = Field(min_length=1, max_length=255)
    locale: Locale
    device: CatalogDevice
    age_rating_limit: AgeRating
    require_available: bool = True
    require_approved_safety: bool = True
    personalization_requested: bool = False
    require_personalization: bool = False

    @model_validator(mode="after")
    def validate_values(self) -> "EligibilityConstraints":
        _require_nonblank(self.tenant_id)
        if self.require_personalization and not self.personalization_requested:
            raise ValueError("personalization is required only when requested")
        return self


class EligibilityDecision(_DomainModel):
    eligible: bool
    reason_code: EligibilityReasonCode
    personalization_allowed: bool


_AGE_ORDER = {AgeRating.E: 0, AgeRating.E10: 1, AgeRating.T: 2}


def evaluate_eligibility(
    experience: ExperienceRecord | None,
    user: UserProfile | None,
    context: ImmersiveDiscoveryContext | None,
    constraints: EligibilityConstraints | None = None,
) -> EligibilityDecision:
    """Apply deterministic hard policy before any model score or ranking."""
    if experience is None or user is None or context is None:
        return EligibilityDecision(
            eligible=False,
            reason_code=EligibilityReasonCode.MISSING_CONTEXT,
            personalization_allowed=False,
        )

    request = context.request_context
    if constraints is None:
        try:
            locale = Locale(request.locale)
        except ValueError:
            return _deny(EligibilityReasonCode.LOCALE_NOT_SUPPORTED)
        try:
            device = CatalogDevice.DESKTOP if request.device in {"web", "api"} else CatalogDevice(request.device)
        except ValueError:
            return _deny(EligibilityReasonCode.DEVICE_NOT_SUPPORTED)
        effective = EligibilityConstraints(
            tenant_id=request.tenant_id,
            locale=locale,
            device=device,
            age_rating_limit=user.age_rating_limit,
            personalization_requested=context.surface in {"home", "recommendation", "related"},
        )
    else:
        effective = constraints
    if user.tenant_id != request.tenant_id or experience.tenant_id != effective.tenant_id:
        return _deny(EligibilityReasonCode.TENANT_SCOPE_MISMATCH)
    if _AGE_ORDER[experience.age_rating] > _AGE_ORDER[effective.age_rating_limit]:
        return _deny(EligibilityReasonCode.AGE_RATING_EXCEEDS_PROFILE_LIMIT)
    if effective.require_approved_safety and experience.safety_state is not SafetyState.APPROVED:
        return _deny(EligibilityReasonCode.SAFETY_STATE_RESTRICTED)
    if effective.require_available and experience.availability is not Availability.AVAILABLE:
        return _deny(EligibilityReasonCode.EXPERIENCE_UNAVAILABLE)
    if effective.locale not in experience.locales:
        return _deny(EligibilityReasonCode.LOCALE_NOT_SUPPORTED)
    if effective.device not in experience.devices:
        return _deny(EligibilityReasonCode.DEVICE_NOT_SUPPORTED)
    if effective.personalization_requested and user.consent_state is ConsentState.PERSONALIZATION_DENIED:
        if effective.require_personalization:
            return _deny(EligibilityReasonCode.PERSONALIZATION_CONSENT_REQUIRED)
        return EligibilityDecision(
            eligible=True,
            reason_code=EligibilityReasonCode.PERSONALIZATION_CONSENT_DENIED,
            personalization_allowed=False,
        )
    return EligibilityDecision(
        eligible=True,
        reason_code=(
            EligibilityReasonCode.SAFE_CATALOG_FALLBACK
            if user.history_length is HistoryLength.NONE
            else EligibilityReasonCode.ALLOW
        ),
        personalization_allowed=effective.personalization_requested,
    )


def _deny(reason_code: EligibilityReasonCode) -> EligibilityDecision:
    return EligibilityDecision(eligible=False, reason_code=reason_code, personalization_allowed=False)


def _require_nonblank(*values: str) -> None:
    if any(not value.strip() for value in values):
        raise ValueError("identifiers and text must be non-empty")
