"""Validated, local-first configuration for the immersive discovery service."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Environment(str, Enum):
    """Environments accepted by the local discovery service."""

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class FeatureFlags(BaseModel):
    """Provider-neutral ranking features with conservative defaults."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    lexical: bool = True
    vector: bool = False
    hybrid: bool = False
    learned: bool = False
    llm: bool = False

    @model_validator(mode="after")
    def validate_composition(self) -> FeatureFlags:
        if self.hybrid and not (self.lexical or self.vector):
            raise ValueError("hybrid search requires lexical or vector search")
        return self


class DiscoverySettings(BaseModel):
    """Runtime settings that are safe to construct without external services."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    environment: Environment = Environment.LOCAL
    profile: str = Field(default="local", min_length=1, max_length=32)
    host: str = Field(default="127.0.0.1", min_length=1, max_length=253)
    port: int = Field(default=8000, ge=1, le=65535)
    fake_provider: bool = True
    no_model: bool = True
    auth_enabled: bool = False
    tls_enabled: bool = False
    audit_logging_enabled: bool = False
    max_request_events: int = Field(default=100, ge=1, le=1000)
    request_timeout_seconds: float = Field(default=5.0, gt=0.0, le=60.0)
    candidate_cap: int = Field(default=100, ge=1, le=1000)
    features: FeatureFlags = Field(default_factory=FeatureFlags)

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> DiscoverySettings:
        if self.environment in {Environment.LOCAL, Environment.TEST}:
            if self.profile not in {"local", "test"}:
                raise ValueError("local and test environments require a matching profile")
        elif self.profile in {"local", "test"}:
            raise ValueError("staging and production require a non-local profile")

        if self.no_model and (self.features.learned or self.features.llm):
            raise ValueError("learned and llm features require no_model=False")
        if self.environment is Environment.PRODUCTION:
            required = {
                "fake_provider": self.fake_provider,
                "no_model": self.no_model,
                "auth_enabled": self.auth_enabled,
                "tls_enabled": self.tls_enabled,
                "audit_logging_enabled": self.audit_logging_enabled,
            }
            unsafe = [name for name, enabled in required.items() if enabled is not False]
            if unsafe:
                raise ValueError(
                    "production requires real providers and auth, TLS, and audit safeguards"
                )
        return self

    def redacted_dump(self) -> dict[str, Any]:
        """Return the serializable configuration without secret material."""

        return self.model_dump(mode="json")


def _parse_bool(value: str, *, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def settings_from_env(environ: Mapping[str, str] | None = None) -> DiscoverySettings:
    """Build settings from ``DISCOVERY_`` variables without reading secrets."""

    values: dict[str, Any] = {}
    source = os.environ if environ is None else environ
    names = {
        "ENVIRONMENT": "environment",
        "PROFILE": "profile",
        "HOST": "host",
        "PORT": "port",
        "FAKE_PROVIDER": "fake_provider",
        "NO_MODEL": "no_model",
        "AUTH_ENABLED": "auth_enabled",
        "TLS_ENABLED": "tls_enabled",
        "AUDIT_LOGGING_ENABLED": "audit_logging_enabled",
        "MAX_REQUEST_EVENTS": "max_request_events",
        "REQUEST_TIMEOUT_SECONDS": "request_timeout_seconds",
        "CANDIDATE_CAP": "candidate_cap",
    }
    bool_fields = {
        "fake_provider",
        "no_model",
        "auth_enabled",
        "tls_enabled",
        "audit_logging_enabled",
    }
    int_fields = {"port", "max_request_events", "candidate_cap"}
    float_fields = {"request_timeout_seconds"}
    for suffix, field_name in names.items():
        raw = source.get(f"DISCOVERY_{suffix}")
        if raw is None:
            continue
        if field_name in bool_fields:
            values[field_name] = _parse_bool(raw, name=f"DISCOVERY_{suffix}")
        elif field_name in int_fields:
            values[field_name] = int(raw)
        elif field_name in float_fields:
            values[field_name] = float(raw)
        elif field_name == "environment":
            values[field_name] = Environment(raw.strip().lower())
        else:
            values[field_name] = raw

    feature_values = {}
    for suffix, field_name in {
        "LEXICAL": "lexical",
        "VECTOR": "vector",
        "HYBRID": "hybrid",
        "LEARNED": "learned",
        "LLM": "llm",
    }.items():
        raw = source.get(f"DISCOVERY_FEATURE_{suffix}")
        if raw is not None:
            feature_values[field_name] = _parse_bool(raw, name=f"DISCOVERY_FEATURE_{suffix}")
    if feature_values:
        values["features"] = FeatureFlags(**feature_values)
    return DiscoverySettings(**values)


load_settings = settings_from_env
