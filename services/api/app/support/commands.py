"""Versioned, untrusted support command contracts.

This module describes proposals only. Policy, persistence, approval, and
execution deliberately remain outside the contract.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SupportCommandModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SupportCommandType(str, Enum):
    ADD_INTERNAL_NOTE = "add_internal_note"
    ASSIGN_TICKET = "assign_ticket"
    SEND_CUSTOMER_REPLY = "send_customer_reply"
    UPDATE_TICKET_STATUS = "update_ticket_status"


class SupportRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SupportApprovalRequirement(str, Enum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"


class SupportTenantPrincipalContext(SupportCommandModel):
    tenant_id: str = Field(min_length=1, max_length=255)
    principal_id: str = Field(min_length=1, max_length=255)

    @field_validator("tenant_id", "principal_id", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("tenant and principal identifiers cannot be blank")
        return value.strip()


_PARAMETER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SCALAR = (str, int, float, bool)
SupportParameterValue = str | int | float | bool


class SupportCommand(SupportCommandModel):
    """A bounded proposal that is safe to pass between resolution stages."""

    command_type: SupportCommandType
    parameters: dict[str, SupportParameterValue] = Field(default_factory=dict, max_length=16)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=1, max_length=255)
    risk_level: SupportRiskLevel
    approval_requirement: SupportApprovalRequirement
    contract_version: str = Field(min_length=1, max_length=32)
    context: SupportTenantPrincipalContext

    @field_validator("idempotency_key", "contract_version", mode="before")
    @classmethod
    def _bounded_text(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip()

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def _evidence(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("evidence_ids must be a non-empty sequence")
        ids = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
        if len(ids) != len(value):
            raise ValueError("evidence_ids must contain non-blank strings")
        if len(set(ids)) != len(ids):
            raise ValueError("evidence_ids must not contain duplicates")
        if any(len(item) > 255 for item in ids):
            raise ValueError("evidence IDs are too long")
        return ids

    @field_validator("parameters", mode="before")
    @classmethod
    def _parameters(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or len(value) > 16:
            raise ValueError("parameters must be a bounded mapping")
        for key, item in value.items():
            if not isinstance(key, str) or not _PARAMETER_NAME.fullmatch(key):
                raise ValueError("parameter names are invalid")
            if not isinstance(item, _SCALAR) or (isinstance(item, str) and len(item) > 1000):
                raise ValueError("parameters must contain bounded scalar values")
        return value

    @model_validator(mode="after")
    def _risk_requires_approval(self) -> SupportCommand:
        if self.risk_level in (SupportRiskLevel.MEDIUM, SupportRiskLevel.HIGH):
            if self.approval_requirement is not SupportApprovalRequirement.REQUIRED:
                raise ValueError("medium and high risk commands require approval")
        return self


# Short aliases keep the contract pleasant to import while retaining explicit
# names for integrations that prefer the longer domain terminology.
RiskLevel = SupportRiskLevel
ApprovalRequirement = SupportApprovalRequirement
TenantPrincipalContext = SupportTenantPrincipalContext
