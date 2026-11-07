"""Validated, local-first configuration for the immersive discovery service."""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any, Literal, Mapping

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
    search_backend: Literal["memory", "opensearch"] = "memory"
    opensearch_url: str | None = Field(default=None, max_length=512)
    opensearch_username: str | None = Field(default=None, max_length=255)
    opensearch_password: str | None = Field(default=None, max_length=512, repr=False)
    opensearch_verify_tls: bool = True
    embedding_provider: Literal["hashing", "azure_openai"] = "hashing"
    embedding_dimensions: int = Field(default=384, ge=8, le=4096)
    embedding_max_texts: int = Field(default=1000, ge=1, le=1_000_000)
    azure_openai_endpoint: str | None = Field(default=None, max_length=512)
    azure_openai_deployment: str | None = Field(default=None, max_length=255)
    azure_openai_api_key: str | None = Field(default=None, max_length=512, repr=False)
    azure_openai_api_version: str = Field(default="2024-10-21", max_length=32)
    azure_openai_auth: Literal["key", "managed_identity", "az_cli"] = "key"
    entra_tenant_id: str | None = Field(default=None, max_length=64)
    entra_audience: str | None = Field(default=None, max_length=255)
    entra_jwks_url: str | None = Field(default=None, max_length=512)
    entra_required_scope: str | None = Field(default=None, max_length=128)
    entra_tenant_map: dict[str, str] = Field(default_factory=dict)
    entra_principal_map: dict[str, str] = Field(default_factory=dict)
    features: FeatureFlags = Field(default_factory=FeatureFlags)

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> DiscoverySettings:
        if self.environment in {Environment.LOCAL, Environment.TEST}:
            if self.profile not in {"local", "test"}:
                raise ValueError("local and test environments require a matching profile")
        elif self.profile in {"local", "test"}:
            raise ValueError("staging and production require a non-local profile")

        if self.search_backend == "opensearch":
            if not self.opensearch_url:
                raise ValueError("search_backend=opensearch requires opensearch_url")
            if self.environment in {Environment.STAGING, Environment.PRODUCTION}:
                if not self.opensearch_url.startswith("https://"):
                    raise ValueError("staging and production require an https opensearch_url")
                if not (self.opensearch_username and self.opensearch_password):
                    raise ValueError("staging and production require opensearch credentials")
                if not self.opensearch_verify_tls and self.environment is Environment.PRODUCTION:
                    raise ValueError("production requires TLS verification for opensearch")
        if self.embedding_provider == "azure_openai":
            if self.no_model:
                raise ValueError("embedding_provider=azure_openai is a model call and requires no_model=False")
            if self.search_backend != "opensearch":
                raise ValueError("embedding_provider=azure_openai requires search_backend=opensearch")
            if not (self.azure_openai_endpoint and self.azure_openai_deployment):
                raise ValueError("azure_openai needs an endpoint and a deployment")
            if self.azure_openai_auth == "key" and not self.azure_openai_api_key:
                raise ValueError("azure_openai_auth=key needs an api key (or use managed_identity or az_cli)")
            if self.azure_openai_auth != "key" and self.azure_openai_api_key:
                raise ValueError("an api key is set but azure_openai_auth is not key; remove the key or the mode")
            if not self.azure_openai_endpoint.startswith("https://"):
                raise ValueError("azure_openai_endpoint must be https")
        if self.auth_enabled:
            if not (self.entra_tenant_id and self.entra_audience):
                raise ValueError("auth_enabled requires entra_tenant_id and entra_audience")
            if self.entra_tenant_map.get(self.entra_tenant_id) in (None, ""):
                raise ValueError("auth_enabled requires entra_tenant_map to map entra_tenant_id to a tenant")
            if self.entra_jwks_url and self.environment in {Environment.STAGING, Environment.PRODUCTION}:
                if not self.entra_jwks_url.startswith("https://"):
                    raise ValueError("staging and production require an https entra_jwks_url")
        if self.no_model and (self.features.learned or self.features.llm):
            raise ValueError("learned and llm features require no_model=False")
        if self.environment is Environment.PRODUCTION:
            # Production must not run on fake providers, and must have auth, TLS and audit logging on.
            # `no_model` is deliberately unconstrained: a deterministic, model-free ranker is a valid
            # production choice, and learned/LLM features are already gated on `no_model=False` above.
            unsafe = [
                name
                for name, ok in {
                    "fake_provider": self.fake_provider is False,
                    "auth_enabled": self.auth_enabled is True,
                    "tls_enabled": self.tls_enabled is True,
                    "audit_logging_enabled": self.audit_logging_enabled is True,
                }.items()
                if not ok
            ]
            if unsafe:
                raise ValueError(
                    "production requires real providers and auth, TLS, and audit safeguards: " + ", ".join(unsafe)
                )
        return self

    def redacted_dump(self) -> dict[str, Any]:
        """Return the serializable configuration without secret material."""

        dump = self.model_dump(mode="json", exclude={"opensearch_password", "azure_openai_api_key"})
        dump["opensearch_password_set"] = bool(self.opensearch_password)
        dump["azure_openai_credential_set"] = bool(self.azure_openai_api_key)
        return dump


def _parse_string_map(value: str, *, name: str) -> dict[str, str]:
    try:
        parsed = json.loads(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a JSON object of strings") from exc
    if not isinstance(parsed, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()):
        raise ValueError(f"{name} must be a JSON object of strings")
    return parsed


def _parse_bool(value: str, *, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def settings_from_env(environ: Mapping[str, str] | None = None) -> DiscoverySettings:
    """Build settings from ``DISCOVERY_`` variables; the OpenSearch password is held but never dumped."""

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
        "SEARCH_BACKEND": "search_backend",
        "OPENSEARCH_URL": "opensearch_url",
        "OPENSEARCH_USERNAME": "opensearch_username",
        "OPENSEARCH_PASSWORD": "opensearch_password",
        "OPENSEARCH_VERIFY_TLS": "opensearch_verify_tls",
        "EMBEDDING_PROVIDER": "embedding_provider",
        "EMBEDDING_DIMENSIONS": "embedding_dimensions",
        "EMBEDDING_MAX_TEXTS": "embedding_max_texts",
        "AZURE_OPENAI_ENDPOINT": "azure_openai_endpoint",
        "AZURE_OPENAI_DEPLOYMENT": "azure_openai_deployment",
        "AZURE_OPENAI_API_KEY": "azure_openai_api_key",
        "AZURE_OPENAI_API_VERSION": "azure_openai_api_version",
        "AZURE_OPENAI_AUTH": "azure_openai_auth",
        "ENTRA_TENANT_ID": "entra_tenant_id",
        "ENTRA_AUDIENCE": "entra_audience",
        "ENTRA_JWKS_URL": "entra_jwks_url",
        "ENTRA_REQUIRED_SCOPE": "entra_required_scope",
        "ENTRA_TENANT_MAP": "entra_tenant_map",
        "ENTRA_PRINCIPAL_MAP": "entra_principal_map",
    }
    bool_fields = {
        "fake_provider",
        "no_model",
        "auth_enabled",
        "tls_enabled",
        "audit_logging_enabled",
        "opensearch_verify_tls",
    }
    int_fields = {"port", "max_request_events", "candidate_cap", "embedding_dimensions", "embedding_max_texts"}
    float_fields = {"request_timeout_seconds"}
    for suffix, field_name in names.items():
        raw = source.get(f"DISCOVERY_{suffix}")
        if raw is None:
            continue
        if field_name in {"entra_tenant_map", "entra_principal_map"}:
            values[field_name] = _parse_string_map(raw, name=f"DISCOVERY_{suffix}")
        elif field_name in bool_fields:
            values[field_name] = _parse_bool(raw, name=f"DISCOVERY_{suffix}")
        elif field_name in int_fields:
            values[field_name] = int(raw)
        elif field_name in float_fields:
            values[field_name] = float(raw)
        elif field_name == "environment":
            values[field_name] = Environment(raw.strip().lower())
        elif field_name in {"search_backend", "azure_openai_auth"}:
            values[field_name] = raw.strip().lower()
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
