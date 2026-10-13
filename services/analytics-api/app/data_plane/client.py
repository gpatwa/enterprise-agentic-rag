"""The control-plane side of the data-plane protocol (ADS-064).

It builds requests and reads metadata-only responses. It imports no gateway, no secret provider, and no credential type: the
control plane names a connection by alias and has no way to hold what the alias resolves to.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from packages.platform_contracts.data_plane import (
    EstimateRequest,
    EstimateResponse,
    ExecuteRequest,
    ExecuteResponse,
    LimitsMessage,
    PlanEnvelope,
    plan_digest,
    requester_ref,
)


class ControlTransport(Protocol):
    """Whatever carries signed requests to the data plane (the simulator here; a network client in a deployment)."""

    def send(self, request: EstimateRequest | ExecuteRequest) -> EstimateResponse | ExecuteResponse: ...


def new_message_id() -> str:
    return uuid.uuid4().hex


class ControlPlaneClient:
    def __init__(self, transport: ControlTransport, *, tenant_id: str, connection_alias: str) -> None:
        self.boundary, self.tenant_id, self.connection_alias = transport, tenant_id, connection_alias

    @staticmethod
    def envelope(plan: Any) -> PlanEnvelope:
        """From any compiled plan (`sql`, `parameters`, `dialect`)."""
        return PlanEnvelope(dialect=plan.dialect, sql=plan.sql, parameters=dict(plan.parameters))

    def estimate(self, *, run_id: str, plan: Any) -> EstimateResponse:
        envelope = self.envelope(plan)
        return self.boundary.send(
            EstimateRequest(
                message_id=new_message_id(),
                tenant_id=self.tenant_id,
                run_id=run_id,
                connection_alias=self.connection_alias,
                plan=envelope,
                plan_fingerprint=plan_digest(envelope),
            )
        )

    def execute(
        self,
        *,
        run_id: str,
        purpose: str,
        user_id: str,
        plan: Any,
        intent: dict,
        contract_ref: str,
        limits: LimitsMessage,
        policy_values: dict | None = None,
    ) -> ExecuteResponse:
        envelope = self.envelope(plan)
        return self.boundary.send(
            ExecuteRequest(
                message_id=new_message_id(),
                tenant_id=self.tenant_id,
                run_id=run_id,
                purpose=purpose,
                requester_ref=requester_ref(self.tenant_id, user_id),
                connection_alias=self.connection_alias,
                plan=envelope,
                plan_fingerprint=plan_digest(envelope),
                intent=intent,
                contract_ref=contract_ref,
                policy_values=policy_values or {},
                limits=limits,
            )
        )
