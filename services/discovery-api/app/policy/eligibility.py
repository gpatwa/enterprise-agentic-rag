"""Fail-closed compilation of discovery eligibility policy.

The result is a provider-neutral expression. A search adapter may translate
these predicates to OpenSearch, SQL, or another provider, but cannot replace
them with scores or profile attributes.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import (
    AgeRating,
    CatalogDevice,
    ConsentState,
    Locale,
    UserProfile,
)
from packages.platform_contracts.discovery import DiscoveryRequestContext

POLICY_VERSION = "imd-eligibility-v1"
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"


class EligibilityReason(str, Enum):
    ALLOW = "allow"
    MISSING_CONTEXT = "missing_context"
    TENANT_SCOPE_MISMATCH = "tenant_scope_mismatch"
    INVALID_LOCALE = "invalid_locale"
    INVALID_DEVICE = "invalid_device"
    PERSONALIZATION_CONSENT_DENIED = "personalization_consent_denied"
    PERSONALIZATION_CONSENT_REQUIRED = "personalization_consent_required"
    INVALID_BLOCKED_ID = "invalid_blocked_id"


class EligibilityPredicate(BaseModel):
    """One allowlisted hard predicate; no scores or private profile data."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    field: Literal[
        "tenant_id",
        "locale",
        "devices",
        "age_rating",
        "safety_state",
        "availability",
        "blocked",
        "experience_id",
    ]
    operator: Literal["eq", "in", "lte", "not_in"]
    value: str | bool | tuple[str, ...]

    @model_validator(mode="after")
    def validate_shape(self) -> "EligibilityPredicate":
        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, tuple) or not self.value:
                raise ValueError("membership predicates require a non-empty tuple")
        elif not isinstance(self.value, (str, bool)):
            raise ValueError("scalar predicates require a string or boolean")
        if self.field == "devices" and self.operator != "in":
            raise ValueError("devices must use membership predicates")
        if self.field == "experience_id" and self.operator != "not_in":
            raise ValueError("experience_id is only valid for blocked IDs")
        return self


class PersonalizationPolicy(BaseModel):
    """Explicit consent outcome, separate from hard catalog eligibility."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    requested: bool = False
    allowed: bool = False
    reason: Literal["not_requested", "consent_granted", "consent_denied"] = "not_requested"

    @model_validator(mode="after")
    def validate_consent(self) -> "PersonalizationPolicy":
        if self.allowed and not self.requested:
            raise ValueError("personalization cannot be allowed when not requested")
        expected = (
            "consent_granted"
            if self.allowed
            else "consent_denied"
            if self.requested
            else "not_requested"
        )
        if self.reason != expected:
            raise ValueError("personalization reason does not match consent outcome")
        return self


class EligibilityCompilation(BaseModel):
    """Deterministic policy decision and its serializable hard-filter expression."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_version: str = POLICY_VERSION
    eligible: bool
    reason: EligibilityReason
    predicates: tuple[EligibilityPredicate, ...] = Field(max_length=32)
    blocked_ids: tuple[str, ...] = Field(max_length=1000)
    personalization: PersonalizationPolicy

    @model_validator(mode="after")
    def validate_blocked_ids(self) -> "EligibilityCompilation":
        if self.blocked_ids != tuple(sorted(set(self.blocked_ids))):
            raise ValueError("blocked IDs must be unique and sorted")
        if any(not item.strip() for item in self.blocked_ids):
            raise ValueError("blocked IDs must be non-blank")
        return self

    def provider_expression(self) -> dict[str, object]:
        """Return only hard predicates for a downstream provider adapter."""
        return {
            "policy_version": self.policy_version,
            "eligible": self.eligible,
            "predicates": [item.model_dump(mode="json") for item in self.predicates],
        }


def compile_eligibility(
    context: DiscoveryRequestContext | None,
    user: UserProfile | None,
    *,
    blocked_ids: tuple[str, ...] = (),
    personalization_requested: bool | None = None,
    require_personalization: bool = False,
) -> EligibilityCompilation:
    """Compile request/profile context into fail-closed hard predicates."""
    normalized_blocked = _normalize_blocked_ids(blocked_ids)
    requested = (
        context.purpose in {"home", "recommendation", "related"}
        if personalization_requested is None and context is not None
        else bool(personalization_requested)
    )
    if context is None or user is None:
        return _denied(EligibilityReason.MISSING_CONTEXT, normalized_blocked, requested)
    if context.tenant_id != user.tenant_id:
        return _denied(EligibilityReason.TENANT_SCOPE_MISMATCH, normalized_blocked, requested)
    try:
        locale = Locale(context.locale)
    except ValueError:
        return _denied(EligibilityReason.INVALID_LOCALE, normalized_blocked, requested)
    try:
        device = CatalogDevice.DESKTOP if context.device in {"web", "api"} else CatalogDevice(context.device)
    except ValueError:
        return _denied(EligibilityReason.INVALID_DEVICE, normalized_blocked, requested)

    allowed = user.consent_state is ConsentState.PERSONALIZATION_ALLOWED
    if require_personalization and (not requested or not allowed):
        reason = EligibilityReason.PERSONALIZATION_CONSENT_REQUIRED
        return _denied(reason, normalized_blocked, requested)
    predicates = _hard_predicates(context.tenant_id, locale, device, user.age_rating_limit, normalized_blocked)
    personalization = _personalization(requested, allowed)
    reason = (
        EligibilityReason.ALLOW
        if not requested or allowed
        else EligibilityReason.PERSONALIZATION_CONSENT_DENIED
    )
    return EligibilityCompilation(
        eligible=True,
        reason=reason,
        predicates=predicates,
        blocked_ids=normalized_blocked,
        personalization=personalization,
    )


def _hard_predicates(
    tenant_id: str,
    locale: Locale,
    device: CatalogDevice,
    age_limit: AgeRating,
    blocked_ids: tuple[str, ...],
) -> tuple[EligibilityPredicate, ...]:
    predicates = [
        EligibilityPredicate(field="tenant_id", operator="eq", value=tenant_id),
        EligibilityPredicate(field="locale", operator="in", value=(locale.value,)),
        EligibilityPredicate(field="devices", operator="in", value=(device.value,)),
        EligibilityPredicate(field="age_rating", operator="lte", value=age_limit.value),
        EligibilityPredicate(field="safety_state", operator="eq", value="approved"),
        EligibilityPredicate(field="availability", operator="eq", value="available"),
        EligibilityPredicate(field="blocked", operator="eq", value=False),
    ]
    if blocked_ids:
        predicates.append(EligibilityPredicate(field="experience_id", operator="not_in", value=blocked_ids))
    return tuple(predicates)


def _personalization(requested: bool, consent_allowed: bool) -> PersonalizationPolicy:
    return PersonalizationPolicy(
        requested=requested,
        allowed=requested and consent_allowed,
        reason="consent_granted" if requested and consent_allowed else "consent_denied" if requested else "not_requested",
    )


def _normalize_blocked_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError("blocked_ids must be a tuple")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("blocked IDs must be non-blank strings")
    if any(re.fullmatch(_IDENTIFIER, value) is None for value in values):
        raise ValueError("blocked IDs contain an invalid value")
    return tuple(sorted(set(values)))


def _denied(reason: EligibilityReason, blocked_ids: tuple[str, ...], requested: bool) -> EligibilityCompilation:
    return EligibilityCompilation(
        eligible=False,
        reason=reason,
        predicates=(),
        blocked_ids=blocked_ids,
        personalization=PersonalizationPolicy(
            requested=requested,
            allowed=False,
            reason="consent_denied" if requested else "not_requested",
        ),
    )
