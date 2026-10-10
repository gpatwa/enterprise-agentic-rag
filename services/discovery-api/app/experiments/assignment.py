"""Deterministic, consent-aware experiment assignment and exposure evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ConsentState
from packages.platform_contracts.discovery import DiscoveryComponentVersion

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_MAX_VARIANTS = 32
_MAX_COMPONENTS = 20
_BUCKETS = 100_000


class _ExperimentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AssignmentRejection(str, Enum):
    """Stable reasons for a request that cannot enter an experiment."""

    NOT_ALLOWLISTED = "not_allowlisted"
    TENANT_NOT_ALLOWED = "tenant_not_allowed"
    CONSENT_REQUIRED = "consent_required"


class ExperimentVariant(_ExperimentModel):
    """One mutually exclusive variant in a bounded experiment."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    allocation: int = Field(default=1, ge=1, le=100_000)


class ExperimentConfig(_ExperimentModel):
    """Allowlisted configuration used as the assignment contract."""

    experiment_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    assignment_version: str = Field(default="v1", min_length=1, max_length=128, pattern=_VERSION)
    variants: tuple[ExperimentVariant, ...] = Field(min_length=2, max_length=_MAX_VARIANTS)
    allowed_tenants: tuple[str, ...] = Field(min_length=1, max_length=1_000)
    component_versions: tuple[DiscoveryComponentVersion, ...] = Field(
        min_length=1, max_length=_MAX_COMPONENTS
    )
    allowlisted: bool = True
    consent_required: bool = True

    @model_validator(mode="after")
    def validate_configuration(self) -> "ExperimentConfig":
        names = tuple(variant.name for variant in self.variants)
        if len(names) != len(set(names)):
            raise ValueError("experiment variants must be mutually exclusive")
        if any(not tenant.strip() for tenant in self.allowed_tenants):
            raise ValueError("allowed tenant identifiers must be non-empty")
        if len(set(self.allowed_tenants)) != len(self.allowed_tenants):
            raise ValueError("allowed tenants must be unique")
        if sum(variant.allocation for variant in self.variants) > _BUCKETS:
            raise ValueError("variant allocations must fit the assignment bucket range")
        return self


class ExperimentAssignment(_ExperimentModel):
    """Redacted stable assignment returned to the caller."""

    schema_version: str = "v1"
    experiment_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    assignment_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    tenant_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant: str = Field(min_length=1, max_length=64)
    bucket: int = Field(ge=0, lt=_BUCKETS)
    component_versions: tuple[DiscoveryComponentVersion, ...] = Field(max_length=_MAX_COMPONENTS)


class ExposureRecord(_ExperimentModel):
    """Immutable exposure evidence without raw identity, query, or profile data."""

    schema_version: str = "v1"
    exposure_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    assignment_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    tenant_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant: str = Field(min_length=1, max_length=64)
    bucket: int = Field(ge=0, lt=_BUCKETS)
    component_versions: tuple[DiscoveryComponentVersion, ...] = Field(
        min_length=1, max_length=_MAX_COMPONENTS
    )
    exposed_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> "ExposureRecord":
        if self.exposed_at.tzinfo is None or self.exposed_at.utcoffset() is None:
            raise ValueError("exposed_at must be timezone-aware")
        return self


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bucket(config: ExperimentConfig, tenant_id: str, user_id: str) -> int:
    identity = f"{config.assignment_version}:{tenant_id}:{user_id}:{config.experiment_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % _BUCKETS


def _variant(config: ExperimentConfig, bucket: int) -> str:
    total = sum(variant.allocation for variant in config.variants)
    normalized = bucket % total
    cursor = 0
    for variant in config.variants:
        cursor += variant.allocation
        if normalized < cursor:
            return variant.name
    raise ValueError("variant allocations do not cover the assignment bucket")


class ExperimentAssigner:
    """Assign stable variants and retain bounded append-only exposure records."""

    def __init__(self) -> None:
        self._exposures: dict[str, ExposureRecord] = {}
        self._lock = Lock()

    def assign(
        self,
        config: ExperimentConfig,
        *,
        tenant_id: str,
        user_id: str,
        consent_state: ConsentState = ConsentState.PERSONALIZATION_ALLOWED,
    ) -> ExperimentAssignment:
        if not config.allowlisted:
            raise ValueError(AssignmentRejection.NOT_ALLOWLISTED.value)
        if tenant_id not in config.allowed_tenants:
            raise ValueError(AssignmentRejection.TENANT_NOT_ALLOWED.value)
        if config.consent_required and consent_state is not ConsentState.PERSONALIZATION_ALLOWED:
            raise ValueError(AssignmentRejection.CONSENT_REQUIRED.value)
        if not tenant_id.strip() or not user_id.strip():
            raise ValueError("tenant_id and user_id must be non-empty")
        bucket = _bucket(config, tenant_id, user_id)
        values = dict(
            schema_version="v1",
            experiment_id=config.experiment_id,
            assignment_version=config.assignment_version,
            tenant_digest=_digest(tenant_id),
            user_digest=_digest(user_id),
            experiment_digest=_digest(f"{config.experiment_id}:{config.assignment_version}"),
            variant=_variant(config, bucket),
            bucket=bucket,
            component_versions=config.component_versions,
        )
        return ExperimentAssignment(**values)

    def expose(
        self, assignment: ExperimentAssignment, *, exposed_at: datetime | None = None
    ) -> ExposureRecord:
        timestamp = exposed_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("exposed_at must be timezone-aware")
        payload = assignment.model_dump()
        canonical = assignment.model_dump(mode="json")
        exposure_id = _digest(json.dumps(canonical, sort_keys=True, separators=(",", ":")))
        record = ExposureRecord(
            **payload,
            exposure_id=exposure_id,
            exposed_at=timestamp,
        )
        with self._lock:
            self._exposures.setdefault(exposure_id, record)
            return self._exposures[exposure_id]

    @property
    def exposures(self) -> tuple[ExposureRecord, ...]:
        with self._lock:
            return tuple(self._exposures.values())


def assign_experiment(
    config: ExperimentConfig,
    *,
    tenant_id: str,
    user_id: str,
    consent_state: ConsentState = ConsentState.PERSONALIZATION_ALLOWED,
) -> ExperimentAssignment:
    """Convenience function for callers that do not need an exposure store."""
    return ExperimentAssigner().assign(
        config, tenant_id=tenant_id, user_id=user_id, consent_state=consent_state
    )
