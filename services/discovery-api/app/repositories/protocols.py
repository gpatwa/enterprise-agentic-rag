"""Bounded, provider-neutral repository protocols for discovery."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ExperienceRecord, UserProfile
from app.events.models import InteractionEvent, InteractionEventBatch

_T = TypeVar("_T")
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"


class _RepositoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PageRequest(_RepositoryModel):
    """A bounded, opaque-cursor page request."""

    limit: int = Field(default=50, ge=1, le=1_000)
    cursor: str | None = Field(default=None, min_length=1, max_length=255, pattern=_IDENTIFIER)


@dataclass(frozen=True)
class Page(Generic[_T]):
    """A repository page with an opaque cursor for the next page."""

    items: tuple[_T, ...]
    next_cursor: str | None = None


class AppendReceipt(_RepositoryModel):
    """The explicit result of an idempotent append attempt."""

    accepted: int = Field(ge=0, le=1_000)
    already_present: int = Field(ge=0, le=1_000)

    @model_validator(mode="after")
    def validate_total(self) -> "AppendReceipt":
        if self.accepted + self.already_present > 1_000:
            raise ValueError("append receipt cannot exceed the batch bound")
        return self


class DerivedFeatureRecord(_RepositoryModel):
    """A rebuildable feature projection, separate from authoritative records."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_IDENTIFIER)
    subject_type: Literal["user", "experience"]
    subject_id: str = Field(min_length=1, max_length=255, pattern=_IDENTIFIER)
    feature_version: str = Field(min_length=1, max_length=255, pattern=_IDENTIFIER)
    values: tuple[tuple[str, float], ...] = Field(max_length=256)
    computed_at: datetime
    source_watermark: str | None = Field(default=None, max_length=255, pattern=_IDENTIFIER)

    @model_validator(mode="after")
    def validate_values(self) -> "DerivedFeatureRecord":
        if self.computed_at.tzinfo is None or self.computed_at.utcoffset() is None:
            raise ValueError("computed_at must be timezone-aware")
        if any(not name.strip() for name, _ in self.values):
            raise ValueError("feature names must be non-empty")
        if len({name for name, _ in self.values}) != len(self.values):
            raise ValueError("feature names must be unique")
        return self


@runtime_checkable
class CatalogRepository(Protocol):
    """Authoritative catalog records; search indexes are not repository authority."""

    def get_experience(self, tenant_id: str, experience_id: str) -> ExperienceRecord | None:
        """Read one authoritative record within an explicit tenant scope."""

    def list_experiences(self, tenant_id: str, page: PageRequest) -> Page[ExperienceRecord]:
        """Read a bounded page of authoritative records for one tenant."""

    def put_experience(self, tenant_id: str, record: ExperienceRecord) -> None:
        """Create or replace one authoritative record within its tenant scope."""


@runtime_checkable
class EventRepository(Protocol):
    """Append-only canonical interaction events and bounded tenant-scoped reads."""

    def append_events(self, tenant_id: str, batch: InteractionEventBatch) -> AppendReceipt:
        """Append a batch idempotently; existing event IDs must remain unchanged."""

    def list_events(self, tenant_id: str, user_id: str, page: PageRequest) -> Page[InteractionEvent]:
        """Read a bounded event page for one tenant and user."""


@runtime_checkable
class ProfileRepository(Protocol):
    """Authoritative user profile records, kept separate from derived features."""

    def get_profile(self, tenant_id: str, user_id: str) -> UserProfile | None:
        """Read one authoritative profile within an explicit tenant scope."""

    def list_profiles(self, tenant_id: str, page: PageRequest) -> Page[UserProfile]:
        """Read a bounded page of authoritative profiles for one tenant."""

    def put_profile(self, tenant_id: str, profile: UserProfile) -> None:
        """Create or replace one authoritative profile within its tenant scope."""


@runtime_checkable
class FeatureRepository(Protocol):
    """Rebuildable derived features, never the authority for catalog or profiles."""

    def get_features(
        self,
        tenant_id: str,
        subject_type: Literal["user", "experience"],
        subject_id: str,
        feature_version: str,
    ) -> DerivedFeatureRecord | None:
        """Read one versioned derived feature projection."""

    def list_features(
        self,
        tenant_id: str,
        subject_type: Literal["user", "experience"],
        page: PageRequest,
        feature_version: str,
    ) -> Page[DerivedFeatureRecord]:
        """Read a bounded page of derived features for one tenant and version."""

    def put_features(self, record: DerivedFeatureRecord) -> None:
        """Replace one derived projection; canonical records remain elsewhere."""
