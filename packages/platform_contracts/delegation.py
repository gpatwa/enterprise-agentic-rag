"""Delegated-purpose policy: what an acting agent may do on a person's behalf (ADS-063).

A delegated token names an acting party (RFC 8693 `act`). The acting party is looked up here by ID. A delegated call
receives only the intersection of the person's purposes and groups with the agent's grant, so an agent can never exceed
either side. The policy itself must be *approved* by a person before any delegation is honoured; until then every
delegated token is refused. Delegated callers are agents for separation of duties: they can never decide a review.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DELEGATION_POLICY_VERSION = "v1"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DelegationApproval(_Frozen):
    status: Literal["proposed", "approved"]
    approved_by: str | None = None
    approved_at: str | None = None
    note: str | None = None


class AgentGrant(_Frozen):
    agent_id: str = Field(min_length=1, max_length=255)
    purposes: tuple[str, ...] = Field(min_length=1, max_length=20)
    groups: tuple[str, ...] = Field(default=(), max_length=20)
    tenants: tuple[str, ...] = Field(default=(), max_length=100)  # empty: every tenant the token names


class DelegationPolicy(_Frozen):
    policy_version: str = Field(min_length=1, max_length=64)
    grants: tuple[AgentGrant, ...] = ()
    approval: DelegationApproval

    @model_validator(mode="after")
    def sane(self) -> "DelegationPolicy":
        ids = [grant.agent_id for grant in self.grants]
        if len(ids) != len(set(ids)):
            raise ValueError("an agent has at most one grant")
        if self.approval.status == "approved" and not (self.approval.approved_by and self.approval.approved_at):
            raise ValueError("an approved policy records who approved it and when")
        return self

    @property
    def approved(self) -> bool:
        return self.approval.status == "approved"

    def grant_for(self, agent_id: str, tenant_id: str) -> AgentGrant | None:
        for grant in self.grants:
            if grant.agent_id == agent_id and (not grant.tenants or tenant_id in grant.tenants):
                return grant
        return None
