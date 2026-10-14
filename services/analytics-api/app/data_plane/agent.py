"""The customer-side data-plane agent (ADS-064).

It sits inside the customer's network: it holds the warehouse credentials (read from the customer's secret provider and never
returned), runs the control plane's compiled query under the control plane's limits, validates the result against the certified
intent *locally* (ADS-041, including the control-total reconciliation), keeps the rows, and answers the control plane with
metadata, fingerprints, and a validation verdict only. Rows go to the end user directly, on a path that needs the user's own
identity token for this plane's issuer.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from app.compiler.postgres import CompiledQuery
from app.execution.gateway import ExecutionError, ExecutionLimits
from app.execution.result_validation import _canonical, plan_fingerprint, run_control_totals, validate_result
from app.security import AuthenticationError, IdentityResolver
from app.security.secrets import SecretProvider
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.data_plane import (
    DATA_PLANE_PROTOCOL,
    DeliveryHandle,
    Envelope,
    EstimateRequest,
    EstimateResponse,
    ExecuteRequest,
    ExecuteResponse,
    FetchResponse,
    PlanEnvelope,
    ValidationVerdict,
    plan_digest,
    requester_ref,
)


class DataPlaneError(Exception):
    """A client-path refusal; `code` is stable and carries no content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ConnectionSpec:
    tenant_id: str
    dialect: str
    secret_name: str
    factory: Callable[[str], Any]  # (credential) -> an ExecutionGateway; the credential never leaves this process


@dataclass
class _Stored:
    tenant_id: str
    run_id: str
    purpose: str
    requester: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    expires_at: datetime


def sign(key: bytes, *, message_id: str, issued_at: datetime, kind: str, body: str) -> str:
    material = "\n".join((DATA_PLANE_PROTOCOL, message_id, issued_at.isoformat(), kind, body)).encode()
    return hmac.new(key, material, hashlib.sha256).hexdigest()


class DataPlaneAgent:
    def __init__(
        self,
        *,
        connections: Mapping[str, ConnectionSpec],
        secrets_provider: SecretProvider,
        contracts: Any,
        compilers: Mapping[str, Any],
        client_resolver: IdentityResolver,
        channel_key: bytes,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        handle_ttl: timedelta = timedelta(minutes=10),
        replay_window: timedelta = timedelta(minutes=5),
        min_cohort: int | None = None,
    ) -> None:
        self._connections, self._secrets, self._contracts = dict(connections), secrets_provider, contracts
        self._compilers, self._resolver, self._key = dict(compilers), client_resolver, channel_key
        self._clock, self._ttl, self._window = clock, handle_ttl, replay_window
        self._min_cohort = min_cohort
        self._gateways: dict[str, Any] = {}
        self._results: dict[str, _Stored] = {}
        self._seen: dict[str, datetime] = {}
        self._lock = threading.Lock()

    # ---- control-plane path: signed envelopes in, metadata out ----

    def handle(self, envelope: Envelope) -> str:
        now = self._clock()
        kind = envelope.kind
        refused = self._refusal(envelope, now)
        if refused:
            return self._error(kind, envelope.message_id, refused)
        try:
            if kind == "estimate":
                return self._estimate(EstimateRequest.model_validate_json(envelope.body)).model_dump_json()
            return self._execute(ExecuteRequest.model_validate_json(envelope.body), now).model_dump_json()
        except ValidationError:
            return self._error(kind, envelope.message_id, "invalid_message")
        except Exception:  # noqa: BLE001 - nothing from an exception (it may name a credential or a value) leaves the plane.
            return self._error(kind, envelope.message_id, "data_plane_error")

    def _refusal(self, envelope: Envelope, now: datetime) -> str | None:
        expected = sign(
            self._key,
            message_id=envelope.message_id,
            issued_at=envelope.issued_at,
            kind=envelope.kind,
            body=envelope.body,
        )
        if not hmac.compare_digest(expected, envelope.signature):
            return "bad_signature"
        if abs(now - envelope.issued_at) > self._window:
            return "stale_message"
        with self._lock:
            self._seen = {key: seen for key, seen in self._seen.items() if now - seen <= self._window}
            if envelope.message_id in self._seen:
                return "replayed_message"
            self._seen[envelope.message_id] = now
        return None

    @staticmethod
    def _error(kind: str, message_id: str, code: str) -> str:
        model = EstimateResponse if kind == "estimate" else ExecuteResponse
        return model(message_id=message_id, status="error", error_code=code).model_dump_json()

    def _estimate(self, request: EstimateRequest) -> EstimateResponse:
        try:
            plan, gateway = self._prepare(request)
            cost = float(gateway.estimate(plan))
        except _Refusal as exc:
            return EstimateResponse(message_id=request.message_id, status="error", error_code=exc.code)
        except ExecutionError as exc:
            return EstimateResponse(message_id=request.message_id, status="error", error_code=exc.code)
        return EstimateResponse(message_id=request.message_id, status="ok", estimated_cost_units=cost)

    def _execute(self, request: ExecuteRequest, now: datetime) -> ExecuteResponse:
        try:
            plan, gateway = self._prepare(request)
            limits = ExecutionLimits(**request.limits.model_dump())
            result = gateway.execute(plan, limits=limits)
            intent = AnalyticalIntent.model_validate(request.intent)
            contract_id, _, version = request.contract_ref.partition("@")
            contract = self._contracts.get_certified(contract_id, version).contract
            compiler = self._compilers[plan.dialect]
            totals = (
                run_control_totals(
                    intent,
                    contract,
                    compile_plan=lambda i, c: compiler.compile(i, c, dict(request.policy_values)),
                    gateway=gateway,
                    limits=limits,
                )
                if intent.group_by
                else {}
            )
            report = validate_result(
                result, plan, intent, contract, control_totals=totals, min_cohort=self._min_cohort
            )
        except _Refusal as exc:
            return ExecuteResponse(message_id=request.message_id, status="error", error_code=exc.code)
        except ExecutionError as exc:
            return ExecuteResponse(message_id=request.message_id, status="error", error_code=exc.code)
        except (ValidationError, LookupError, KeyError, ValueError):
            return ExecuteResponse(message_id=request.message_id, status="error", error_code="request_unusable")
        handle = secrets.token_hex(16)
        expires = now + self._ttl
        with self._lock:
            self._results[handle] = _Stored(
                tenant_id=request.tenant_id,
                run_id=request.run_id,
                purpose=request.purpose,
                requester=request.requester_ref,
                columns=result.columns,
                rows=tuple(
                    tuple(_canonical(cell) for cell in row) for row in result.rows
                ),  # as the REST rows are: exact
                expires_at=expires,
            )
        return ExecuteResponse(
            message_id=request.message_id,
            status="ok",
            columns=result.columns,
            row_count=result.row_count,
            byte_count=result.byte_count,
            truncated=result.truncated,
            truncation_reason=result.truncation_reason,
            estimated_cost_units=result.estimated_cost_units,
            elapsed_ms=result.elapsed_ms,
            result_fingerprint=report.result_fingerprint,
            validation=ValidationVerdict(
                status=report.status,
                issue_codes=tuple(sorted({i.code for i in report.issues})),
                fingerprint=report.fingerprint,
                result_fingerprint=report.result_fingerprint,
                plan_fingerprint=report.plan_fingerprint,
                checks=report.checks,
            ),
            delivery=DeliveryHandle(handle_id=handle, row_count=result.row_count, expires_at=expires),
        )

    def _prepare(self, request: EstimateRequest) -> tuple[CompiledQuery, Any]:
        spec = self._connections.get(request.connection_alias)
        if spec is None:
            raise _Refusal("unknown_connection")
        if spec.tenant_id != request.tenant_id:
            raise _Refusal("tenant_mismatch")
        plan = _plan(request.plan)
        if plan_digest(request.plan) != request.plan_fingerprint or plan_fingerprint(plan) != request.plan_fingerprint:
            raise _Refusal("plan_fingerprint_mismatch")
        if spec.dialect != plan.dialect:
            raise _Refusal("dialect_mismatch")
        try:
            return plan, self._gateway(request.connection_alias, spec)
        except Exception as exc:  # noqa: BLE001 - a connection failure never reports why (the text may hold a credential).
            raise _Refusal("connection_unavailable") from exc

    def _gateway(self, alias: str, spec: ConnectionSpec) -> Any:
        with self._lock:
            cached = self._gateways.get(alias)
        if cached is not None:
            return cached
        gateway = spec.factory(self._secrets.read(spec.tenant_id, spec.secret_name))
        with self._lock:
            self._gateways[alias] = gateway
        return gateway

    # ---- client path: the user's own token, straight from this plane ----

    def fetch(self, handle_id: str, bearer_token: str) -> FetchResponse:
        try:
            identity = self._resolver.resolve(bearer_token or "")
        except AuthenticationError as exc:
            raise DataPlaneError("unauthenticated") from exc
        now = self._clock()
        with self._lock:
            stored = self._results.get(handle_id)
            if stored is not None and stored.expires_at <= now:
                del self._results[handle_id]
                raise DataPlaneError("handle_expired")
        if (
            stored is None
            or stored.tenant_id != identity.tenant_id
            or stored.requester != requester_ref(identity.tenant_id, identity.user_id)
            or stored.purpose not in identity.purposes
        ):
            raise DataPlaneError(
                "handle_not_found"
            )  # one answer for unknown and for not-yours, so handles cannot be probed
        return FetchResponse(columns=stored.columns, rows=stored.rows)


class _Refusal(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _plan(envelope: PlanEnvelope) -> CompiledQuery:
    return CompiledQuery(sql=envelope.sql, parameters=dict(envelope.parameters), dialect=envelope.dialect)
