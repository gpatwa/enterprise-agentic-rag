"""Deterministic, privacy-aware online feature hydration."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ConsentState
from app.features.materialization import FeatureKind, FeatureRecord
from packages.platform_contracts.discovery import DiscoveryRequestContext

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_MAX_FEATURES = 128
_MAX_AGE_SECONDS = 31_536_000
_PRIVATE_NAMES = {"history", "raw_history", "vector", "embedding", "social_identity", "peer_ids"}


class HydrationStatus(str, Enum):
    HYDRATED = "hydrated"
    DEFAULTED = "defaulted"
    STALE = "stale"
    VERSION_MISMATCH = "version_mismatch"
    FUTURE = "future"
    CONSENT_DENIED = "consent_denied"
    MISSING = "missing"


class _HydrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FeatureHydrationRequest(_HydrationModel):
    """The identity and bounded feature projection for one request."""

    context: DiscoveryRequestContext
    as_of: datetime
    feature_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    subject_type: FeatureKind
    subject_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    feature_names: tuple[str, ...] = Field(min_length=1, max_length=_MAX_FEATURES)
    stale_after_seconds: float = Field(default=3_600.0, ge=0, le=_MAX_AGE_SECONDS, allow_inf_nan=False)
    consent_state: ConsentState = ConsentState.PERSONALIZATION_ALLOWED

    @model_validator(mode="after")
    def validate_request(self) -> "FeatureHydrationRequest":
        _require_aware(self.as_of, "as_of")
        if not self.feature_names or len(set(self.feature_names)) != len(self.feature_names):
            raise ValueError("feature names must be unique and non-empty")
        if any(not name or len(name) > 128 for name in self.feature_names):
            raise ValueError("feature names must be non-empty and at most 128 characters")
        if any(name.lower() in _PRIVATE_NAMES for name in self.feature_names):
            raise ValueError("private feature names are not hydratable")
        return self


class HydratedFeature(_HydrationModel):
    """One safe scalar feature and the reason it was returned."""

    name: str = Field(min_length=1, max_length=128)
    value: float = Field(ge=-1_000_000_000, le=1_000_000_000, allow_inf_nan=False)
    status: HydrationStatus
    feature_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    age_seconds: float = Field(ge=0, le=_MAX_AGE_SECONDS, allow_inf_nan=False)


class FeatureHydrationTrace(_HydrationModel):
    """Redacted evidence; identifiers are digests and raw feature data is absent."""

    tenant_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_count: int = Field(ge=1, le=_MAX_FEATURES)
    defaulted_count: int = Field(ge=0, le=_MAX_FEATURES)
    status: HydrationStatus


class FeatureHydrationResult(_HydrationModel):
    """Bounded scalar features suitable for a provider-neutral ranker."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    subject_type: FeatureKind
    subject_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    feature_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    features: tuple[HydratedFeature, ...] = Field(max_length=_MAX_FEATURES)
    trace: FeatureHydrationTrace


class FeatureHydrator:
    """Hydrate only the requested scalar projection from one materialized record."""

    def hydrate(self, request: FeatureHydrationRequest, record: FeatureRecord | None = None) -> FeatureHydrationResult:
        if record is not None and record.tenant_id != request.context.tenant_id:
            raise ValueError("feature record tenant does not match request")
        if record is not None and (record.subject_type is not request.subject_type or record.subject_id != request.subject_id):
            raise ValueError("feature record subject does not match request")
        age = 0.0 if record is None else _age(request.as_of, record.as_of)
        if record is not None and record.as_of > request.as_of:
            status = HydrationStatus.FUTURE
        elif record is not None and record.feature_version != request.feature_version:
            status = HydrationStatus.VERSION_MISMATCH
        elif record is not None and age > request.stale_after_seconds:
            status = HydrationStatus.STALE
        elif request.consent_state is ConsentState.PERSONALIZATION_DENIED or (
            record is not None and record.consent_state is ConsentState.PERSONALIZATION_DENIED
        ):
            status = HydrationStatus.CONSENT_DENIED
        else:
            status = HydrationStatus.HYDRATED

        values = record.values if status is HydrationStatus.HYDRATED and record is not None else {}
        features = tuple(
            HydratedFeature(
                name=name,
                value=values.get(name, 0.0),
                status=(
                    status
                    if status is not HydrationStatus.HYDRATED
                    else HydrationStatus.HYDRATED if name in values else HydrationStatus.DEFAULTED
                ),
                feature_version=request.feature_version,
                age_seconds=age,
            )
            for name in request.feature_names
        )
        trace_status = status if status is not HydrationStatus.HYDRATED else (
            HydrationStatus.DEFAULTED if len(values) < len(request.feature_names) else HydrationStatus.HYDRATED
        )
        return FeatureHydrationResult(
            tenant_id=request.context.tenant_id,
            request_id=request.context.request_id,
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            feature_version=request.feature_version,
            features=features,
            trace=FeatureHydrationTrace(
                tenant_digest=_digest(request.context.tenant_id),
                request_digest=_digest(request.context.request_id),
                subject_digest=_digest(request.subject_id),
                requested_count=len(request.feature_names),
                defaulted_count=sum(item.status is not HydrationStatus.HYDRATED for item in features),
                status=trace_status,
            ),
        )


def hydrate_features(request: FeatureHydrationRequest, record: FeatureRecord | None = None) -> FeatureHydrationResult:
    """Convenience wrapper for the default hydrator."""
    return FeatureHydrator().hydrate(request, record)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _age(as_of: datetime, produced_at: datetime) -> float:
    _require_aware(produced_at, "record.as_of")
    age = (as_of - produced_at).total_seconds()
    return max(0.0, min(float(age), _MAX_AGE_SECONDS))


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
