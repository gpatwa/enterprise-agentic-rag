"""Append-only audit of tool calls on every transport (ADS-061).

Events carry the tool, transport, outcome, error code, and a *digest* of the arguments: never argument values, SQL, rows,
or tokens. The chain is the existing hash-chained `AuditChain`, serialized by a lock.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any
from uuid import uuid4

from app.security.audit import AuditChain
from packages.platform_contracts.agent_tools import ToolResult
from packages.platform_contracts.security import AnalyticsIdentity, AuditEvent

UNAUTHENTICATED_TENANT = "unauthenticated"


def arguments_digest(arguments: Any) -> str:
    try:
        body = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        body = repr(type(arguments))
    return hashlib.sha256(body.encode()).hexdigest()


class ToolAudit:
    def __init__(self, chain: AuditChain | None = None) -> None:
        self.chain = chain or AuditChain()
        self._lock = threading.Lock()

    @property
    def events(self) -> list[AuditEvent]:
        return list(self.chain.events)

    def record_call(
        self, identity: AnalyticsIdentity, *, tool: str, transport: str, result: ToolResult, arguments: Any
    ) -> AuditEvent:
        run_id = result.run.run_id if result.run else result.evidence.run_id if result.evidence else None
        payload = {
            "tool": tool[:64],
            "transport": transport,
            "ok": result.ok,
            "error_code": result.error.code if result.error else None,
            "arguments_sha256": arguments_digest(arguments),
            "run_id_sha256": hashlib.sha256(run_id.encode()).hexdigest()[:16] if run_id else None,
        }
        return self._append("tool_call", identity.tenant_id, identity.user_id, payload)

    def record_denied(self, *, transport: str, reason: str) -> AuditEvent:
        """An unauthenticated attempt: there is no verified identity, so nothing about the caller is recorded."""
        return self._append(
            "tool_call_unauthenticated", UNAUTHENTICATED_TENANT, "unknown", {"transport": transport, "reason": reason}
        )

    def verify(self) -> bool:
        with self._lock:
            return self.chain.verify()

    def _append(self, event_type: str, tenant_id: str, actor_id: str, payload: dict) -> AuditEvent:
        with self._lock:
            return self.chain.append(uuid4().hex, event_type, tenant_id, actor_id, payload)
