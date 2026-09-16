"""Provider-neutral declarations for tools available to an agent graph.

The registry is a metadata and compatibility boundary. It never executes a
tool, evaluates authorization, or carries model-authored SQL.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TOOL_REGISTRY_SCHEMA_VERSION = "v1"
_ALLOWED_CAPABILITIES = frozenset(
    {
        "context.read", "metadata.read", "semantic.read", "evidence.read", "analytics.explain",
        "search.read", "catalog.read",
    }
)


class ToolRegistryError(ValueError):
    """Base error raised when a tool declaration cannot be admitted."""


class UnsupportedToolVersionError(ToolRegistryError):
    """Raised when a requested tool version is not registered."""


class IncompatibleContractError(ToolRegistryError):
    """Raised when a caller requests unsupported input/output contracts."""


class RiskClass(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=1, ge=1, le=10)
    backoff_ms: int = Field(default=0, ge=0, le=300_000)
    retryable_errors: tuple[str, ...] = ()


class ToolSpec(BaseModel):
    """Immutable, provider-neutral metadata for one versioned tool."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)

    registry_schema_version: Literal["v1"] = TOOL_REGISTRY_SCHEMA_VERSION
    tool_id: str = Field(min_length=1, max_length=255, pattern=r"^[a-z][a-z0-9_.-]*$")
    version: str = Field(min_length=1, max_length=64, pattern=r"^v[1-9][0-9]*$")
    capability: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
    risk_class: RiskClass
    timeout_ms: int = Field(gt=0, le=300_000)
    retry_policy: RetryPolicy = RetryPolicy()
    idempotency_mode: Literal["none", "optional", "required"]
    idempotency_key_required: bool = False
    input_contract_version: str = Field(min_length=1, max_length=64, pattern=r"^v[1-9][0-9]*$")
    output_contract_version: str = Field(min_length=1, max_length=64, pattern=r"^v[1-9][0-9]*$")
    required_scope: Literal["tenant", "purpose", "tenant_and_purpose"]
    allowed_purposes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_metadata(self) -> "ToolSpec":
        if self.idempotency_key_required and self.idempotency_mode != "required":
            raise ValueError("idempotency_key_required requires idempotency_mode=required")
        if self.idempotency_mode == "required" and not self.idempotency_key_required:
            raise ValueError("required idempotency mode requires an idempotency key")
        if self.risk_class == RiskClass.DESTRUCTIVE and self.required_scope != "tenant_and_purpose":
            raise ValueError("destructive tools require tenant_and_purpose scope")
        if any(not purpose or len(purpose) > 255 for purpose in self.allowed_purposes):
            raise ValueError("allowed_purposes must contain non-empty values of at most 255 characters")
        if self.required_scope in {"purpose", "tenant_and_purpose"} and not self.allowed_purposes:
            raise ValueError("purpose-scoped tools require allowed_purposes")
        return self


class ToolMetadata(BaseModel):
    """Metadata returned to callers; deliberately contains no executable handle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_schema_version: Literal["v1"] = TOOL_REGISTRY_SCHEMA_VERSION
    tool_id: str
    version: str
    capability: str
    risk_class: RiskClass
    timeout_ms: int
    retry_policy: RetryPolicy
    idempotency_mode: Literal["none", "optional", "required"]
    idempotency_key_required: bool
    input_contract_version: str
    output_contract_version: str
    required_scope: Literal["tenant", "purpose", "tenant_and_purpose"]
    allowed_purposes: tuple[str, ...]


class ToolRegistry:
    """Fail-closed registry of explicitly declared tool metadata."""

    def __init__(self, specs: tuple[ToolSpec, ...] = ()) -> None:
        self._specs: dict[tuple[str, str], ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.capability not in _ALLOWED_CAPABILITIES:
            raise ToolRegistryError(f"unsafe capability is not registerable: {spec.capability}")
        key = (spec.tool_id, spec.version)
        if key in self._specs:
            raise ToolRegistryError(f"duplicate tool identity: {spec.tool_id}@{spec.version}")
        self._specs[key] = spec

    def lookup(
        self,
        tool_id: str,
        version: str,
        *,
        input_contract_version: str,
        output_contract_version: str,
        tenant_id: str | None = None,
        purpose: str | None = None,
    ) -> ToolMetadata:
        spec = self._specs.get((tool_id, version))
        if spec is None:
            raise UnsupportedToolVersionError(f"undeclared or unsupported tool: {tool_id}@{version}")
        if (
            input_contract_version != spec.input_contract_version
            or output_contract_version != spec.output_contract_version
        ):
            raise IncompatibleContractError(f"incompatible contracts for {tool_id}@{version}")
        if spec.required_scope in {"tenant", "tenant_and_purpose"} and not tenant_id:
            raise ToolRegistryError(f"tenant scope is required for {tool_id}@{version}")
        if spec.required_scope in {"purpose", "tenant_and_purpose"} and purpose not in spec.allowed_purposes:
            raise ToolRegistryError(f"purpose is not allowed for {tool_id}@{version}")
        return ToolMetadata.model_validate(spec.model_dump())

    def metadata(self) -> tuple[ToolMetadata, ...]:
        return tuple(ToolMetadata.model_validate(spec.model_dump()) for spec in self._specs.values())
