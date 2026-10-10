"""Fail-closed routing controls for legacy and governed execution paths."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROUTING_SCHEMA_VERSION = "v1"
RoutingMode = Literal["legacy", "shadow", "governed", "disabled"]
_ALLOWED_MODE_TRANSITIONS: dict[RoutingMode, frozenset[RoutingMode]] = {
    "legacy": frozenset({"legacy", "shadow", "governed", "disabled"}),
    "shadow": frozenset({"legacy", "shadow", "governed", "disabled"}),
    "governed": frozenset({"legacy", "shadow", "governed", "disabled"}),
    "disabled": frozenset({"legacy", "disabled"}),
}


class TrustedAuthorizationArtifact(BaseModel):
    """Short-lived, signed authorization fact issued by a trusted policy boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    rollout_id: str = Field(min_length=1, max_length=255)
    approval_reference: str = Field(min_length=1, max_length=255)
    audit_event_id: str = Field(min_length=1, max_length=255)
    issued_at: datetime
    expires_at: datetime
    signature: str = Field(min_length=64, max_length=64)

    @staticmethod
    def _payload(values: dict[str, object]) -> bytes:
        fields = (
            "artifact_id", "tenant_id", "request_id", "purpose", "rollout_id",
            "approval_reference", "audit_event_id", "issued_at", "expires_at",
        )
        return json.dumps({key: values[key] for key in fields}, sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def issue(cls, *, signing_key: str, issued_at: datetime, expires_at: datetime, **values: str) -> "TrustedAuthorizationArtifact":
        if issued_at.tzinfo is None or expires_at.tzinfo is None or expires_at <= issued_at:
            raise ValueError("authorization artifact timestamps must be ordered and timezone-aware")
        payload = {**values, "issued_at": issued_at.isoformat(), "expires_at": expires_at.isoformat()}
        signature = hmac.new(signing_key.encode(), cls._payload(payload), hashlib.sha256).hexdigest()
        return cls(**payload, signature=signature)

    def verify(self, signing_key: str, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None or current >= self.expires_at:
            return False
        values = self.model_dump()
        values["issued_at"] = self.issued_at.isoformat()
        values["expires_at"] = self.expires_at.isoformat()
        expected = hmac.new(signing_key.encode(), self._payload(values), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.signature)


class RoutingContext(BaseModel):
    """Request and rollout identity required to resolve a route."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    rollout_id: str | None = Field(default=None, min_length=1, max_length=255)
    governed_enabled: bool = False
    approval_reference: str | None = Field(default=None, min_length=1, max_length=255)
    audit_event_id: str | None = Field(default=None, min_length=1, max_length=255)
    authorization_artifact: TrustedAuthorizationArtifact | None = None

    @model_validator(mode="after")
    def require_governed_evidence(self) -> "RoutingContext":
        if self.governed_enabled and not self.rollout_id:
            raise ValueError("governed enablement requires rollout_id")
        if self.governed_enabled and not self.approval_reference:
            raise ValueError("governed enablement requires approval_reference")
        if self.governed_enabled and not self.audit_event_id:
            raise ValueError("governed enablement requires audit_event_id")
        return self


class RoutingConfig(BaseModel):
    """Provider-neutral routing policy; absent tenant overrides use legacy."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["v1"] = ROUTING_SCHEMA_VERSION
    default_mode: RoutingMode = "legacy"
    tenant_modes: dict[str, RoutingMode] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_non_empty_tenant_keys(self) -> "RoutingConfig":
        if any(not tenant_id.strip() for tenant_id in self.tenant_modes):
            raise ValueError("tenant routing keys must be non-empty")
        return self


class RouteDecision(BaseModel):
    """Immutable decision consumed by callers before any governed action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["v1"] = ROUTING_SCHEMA_VERSION
    tenant_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    mode: RoutingMode
    execute_legacy: bool
    execute_governed: bool
    record_shadow: bool
    refusal_reason: str | None = None
    audit_event_id: str | None = None

    @model_validator(mode="after")
    def enforce_mode_capabilities(self) -> "RouteDecision":
        expected = {
            "legacy": (True, False, False),
            "shadow": (True, False, True),
            "governed": (False, True, False),
            "disabled": (False, False, False),
        }[self.mode]
        if (self.execute_legacy, self.execute_governed, self.record_shadow) != expected:
            raise ValueError(f"capabilities do not match {self.mode} routing mode")
        if self.mode == "disabled" and not self.refusal_reason:
            raise ValueError("disabled routing requires refusal_reason")
        if self.mode == "governed" and not self.audit_event_id:
            raise ValueError("governed routing requires audit_event_id")
        return self


class RoutingRefusal(PermissionError):
    """Raised when a route cannot execute the requested governed action."""


class RoutingTransitionError(ValueError):
    """Raised when a rollout attempts an unsupported mode transition."""


def validate_mode_transition(current: RoutingMode, requested: RoutingMode) -> RoutingMode:
    """Validate a mode change before persisting or applying rollout config."""
    allowed = _ALLOWED_MODE_TRANSITIONS.get(current)
    if allowed is None or requested not in _ALLOWED_MODE_TRANSITIONS:
        raise RoutingTransitionError(f"unknown routing mode in transition: {current} -> {requested}")
    if requested not in allowed:
        raise RoutingTransitionError(f"invalid routing transition: {current} -> {requested}")
    return requested


def resolve_route(
    config: RoutingConfig, context: RoutingContext, *, authorization_key: str | None = None
) -> RouteDecision:
    """Resolve a tenant route while keeping governed activation explicit."""
    mode = config.tenant_modes.get(context.tenant_id, config.default_mode)
    if mode == "governed":
        artifact = context.authorization_artifact
        if not context.governed_enabled or artifact is None or not authorization_key:
            raise RoutingRefusal("governed routing requires a trusted authorization artifact")
        if (
            artifact.tenant_id != context.tenant_id
            or artifact.request_id != context.request_id
            or artifact.purpose != context.purpose
            or not artifact.verify(authorization_key)
        ):
            raise RoutingRefusal("governed routing authorization artifact is invalid or mismatched")
        return RouteDecision(
            tenant_id=context.tenant_id,
            request_id=context.request_id,
            mode=mode,
            execute_legacy=False,
            execute_governed=True,
            record_shadow=False,
            audit_event_id=artifact.audit_event_id,
        )
    if mode == "disabled":
        return RouteDecision(
            tenant_id=context.tenant_id,
            request_id=context.request_id,
            mode=mode,
            execute_legacy=False,
            execute_governed=False,
            record_shadow=False,
            refusal_reason="routing is disabled for this tenant",
        )
    if mode == "shadow":
        return RouteDecision(
            tenant_id=context.tenant_id,
            request_id=context.request_id,
            mode=mode,
            execute_legacy=True,
            execute_governed=False,
            record_shadow=True,
        )
    return RouteDecision(
        tenant_id=context.tenant_id,
        request_id=context.request_id,
        mode="legacy",
        execute_legacy=True,
        execute_governed=False,
        record_shadow=False,
    )


def require_governed_action(decision: RouteDecision) -> None:
    """Guard an action boundary; shadow and disabled can never pass it."""
    if decision.mode == "disabled":
        raise RoutingRefusal(decision.refusal_reason or "routing is disabled")
    if not decision.execute_governed:
        raise RoutingRefusal(f"governed action is not permitted in {decision.mode} mode")
