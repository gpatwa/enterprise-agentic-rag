"""Append-only hash chained audit events."""
from __future__ import annotations

import hashlib
import json

from packages.platform_contracts.security import AuditEvent


class AuditChain:
    def __init__(self):
        self.events: list[AuditEvent] = []

    def append(self, event_id: str, event_type: str, tenant_id: str, actor_id: str, payload: dict) -> AuditEvent:
        previous_hash = self.events[-1].event_hash if self.events else None
        body = {"event_id": event_id, "event_type": event_type, "tenant_id": tenant_id, "actor_id": actor_id, "payload": payload, "previous_hash": previous_hash}
        event_hash = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        event = AuditEvent(**body, event_hash=event_hash)
        self.events.append(event)
        return event

    def verify(self) -> bool:
        previous_hash = None
        for event in self.events:
            body = {"event_id": event.event_id, "event_type": event.event_type, "tenant_id": event.tenant_id, "actor_id": event.actor_id, "payload": event.payload, "previous_hash": previous_hash}
            expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if event.previous_hash != previous_hash or event.event_hash != expected:
                return False
            previous_hash = event.event_hash
        return True
