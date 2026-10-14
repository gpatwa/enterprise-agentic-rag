"""Customer data-plane protocol (ADS-064).

The control plane compiles, authorizes, reviews, and records evidence; the data plane lives in the customer's network, holds
the warehouse credentials, executes, and validates. Across the boundary only the messages below may travel. **No message has a
field that can carry result rows or a credential**, models forbid extra fields, and the response carries metadata, fingerprints,
and a validation verdict, never data. Rows reach the end user over a separate client-to-data-plane path, identified by an opaque
handle that is useless without the user's own identity.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DATA_PLANE_PROTOCOL = "data-plane-v1"
_HEX64 = r"^[0-9a-f]{64}$"
_ALIAS = r"^[a-z0-9][a-z0-9_.-]{0,62}$"
Scalar = str | int | float | bool | None


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanEnvelope(_Msg):
    dialect: Literal["duckdb", "postgres"]
    sql: str = Field(min_length=1, max_length=20_000)
    parameters: dict[str, Scalar] = Field(default_factory=dict, max_length=64)


class LimitsMessage(_Msg):
    timeout_seconds: float = Field(gt=0, le=600)
    max_rows: int = Field(gt=0, le=100_000)
    max_bytes: int = Field(gt=0, le=100_000_000)
    max_cost_units: float = Field(gt=0)


class EstimateRequest(_Msg):
    protocol: Literal["data-plane-v1"] = DATA_PLANE_PROTOCOL
    message_id: str = Field(min_length=8, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=255)
    run_id: str = Field(min_length=1, max_length=255)
    connection_alias: str = Field(pattern=_ALIAS)  # a name the customer maps to a credential; never the credential
    plan: PlanEnvelope
    plan_fingerprint: str = Field(pattern=_HEX64)


class ExecuteRequest(EstimateRequest):
    purpose: str = Field(min_length=1, max_length=255)
    requester_ref: str = Field(pattern=_HEX64)  # sha256("tenant:user"): rows are released only to this person
    intent: dict = Field(max_length=64)  # the certified AnalyticalIntent (semantic IDs only)
    contract_ref: str = Field(min_length=3, max_length=512)  # "id@version"; the customer holds the certified contract
    policy_values: dict[str, Scalar | list[Scalar]] = Field(default_factory=dict, max_length=32)
    limits: LimitsMessage


class ValidationVerdict(_Msg):
    status: Literal["valid", "valid_with_warnings", "invalid"]
    issue_codes: tuple[str, ...] = ()
    fingerprint: str = Field(pattern=_HEX64)
    result_fingerprint: str = Field(pattern=_HEX64)
    plan_fingerprint: str = Field(pattern=_HEX64)
    checks: tuple[str, ...] = ()


class DeliveryHandle(_Msg):
    """Opaque and useless alone: rows are released only to the identity that asked, directly from the data plane."""

    handle_id: str = Field(min_length=16, max_length=64)
    row_count: int = Field(ge=0)
    expires_at: datetime


class EstimateResponse(_Msg):
    protocol: Literal["data-plane-v1"] = DATA_PLANE_PROTOCOL
    message_id: str
    status: Literal["ok", "error"]
    error_code: str | None = Field(default=None, max_length=100)
    estimated_cost_units: float | None = Field(default=None, ge=0)


class ExecuteResponse(_Msg):
    protocol: Literal["data-plane-v1"] = DATA_PLANE_PROTOCOL
    message_id: str
    status: Literal["ok", "error"]
    error_code: str | None = Field(default=None, max_length=100)
    columns: tuple[str, ...] = ()
    row_count: int = Field(default=0, ge=0)
    byte_count: int = Field(default=0, ge=0)
    truncated: bool = False
    truncation_reason: Literal["max_rows", "max_bytes"] | None = None
    estimated_cost_units: float | None = Field(default=None, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)
    result_fingerprint: str | None = Field(default=None, pattern=_HEX64)
    validation: ValidationVerdict | None = None
    delivery: DeliveryHandle | None = None


class FetchRequest(_Msg):
    """Client to data plane only. The bearer token is the *user's own* identity token for the data plane's issuer."""

    handle_id: str = Field(min_length=16, max_length=64)


class FetchResponse(_Msg):
    columns: tuple[str, ...]
    rows: tuple[tuple[Scalar, ...], ...]


class Envelope(_Msg):
    """The signed wrapper every control-plane message travels in; the signature is the only trace of the channel key."""

    protocol: Literal["data-plane-v1"] = DATA_PLANE_PROTOCOL
    message_id: str = Field(min_length=8, max_length=128)
    issued_at: datetime
    kind: Literal["estimate", "execute"]
    body: str = Field(max_length=64_000)
    signature: str = Field(pattern=_HEX64)


def plan_digest(plan: PlanEnvelope) -> str:
    """The plan fingerprint both planes compute; it equals `result_validation.plan_fingerprint` for the same plan."""
    body = {
        "dialect": plan.dialect,
        "sql": plan.sql,
        "parameters": {key: _canonical(value) for key, value in sorted(plan.parameters.items())},
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def requester_ref(tenant_id: str, user_id: str) -> str:
    return hashlib.sha256(f"{tenant_id}:{user_id}".encode()).hexdigest()


def _canonical(value: Scalar) -> Scalar:
    return (
        value
        if value is None or isinstance(value, (str, int, bool))
        else repr(value)
        if isinstance(value, float)
        else str(value)
    )
