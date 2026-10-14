"""A local VPC-boundary simulator for the data-plane protocol (ADS-064).

Everything that crosses is serialized to JSON, logged per direction, and scanned for forbidden content (registered result
values and credentials). On the control path a hit is *blocked* and recorded as a violation, so a leaking agent cannot be
mistaken for a working one. Rows travel only on the client path, which is logged separately and is never part of the control
log. This simulates the boundary's contract; it is not network isolation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import BaseModel

from app.data_plane.agent import DataPlaneAgent, sign
from packages.platform_contracts.data_plane import (
    Envelope,
    EstimateRequest,
    EstimateResponse,
    ExecuteRequest,
    ExecuteResponse,
    FetchResponse,
)

CONTROL_OUT, CONTROL_IN, CLIENT_OUT, CLIENT_IN = "control->data", "data->control", "client->data", "data->client"
MAX_MESSAGE_CHARS = 64_000


class BoundaryViolation(Exception):
    """Forbidden content tried to cross the boundary; the message names the direction, never the content."""

    def __init__(self, direction: str, count: int) -> None:
        self.direction, self.count = direction, count
        super().__init__(f"{count} forbidden value(s) in a {direction} message")


@dataclass
class Scanner:
    """The oracle: any registered value appearing in a control-path message is a violation."""

    forbidden: set[str] = field(default_factory=set)

    def register(self, *values: object) -> None:
        self.forbidden.update(str(value) for value in values if str(value))

    def hits(self, text: str) -> list[str]:
        return sorted(value for value in self.forbidden if value in text)


@dataclass
class BoundaryLog:
    records: list[tuple[str, str]] = field(default_factory=list)
    violations: list[tuple[str, int]] = field(default_factory=list)

    def add(self, direction: str, payload: str) -> None:
        self.records.append((direction, payload))

    def text(self, *directions: str) -> str:
        return "\n".join(payload for direction, payload in self.records if direction in directions)

    def control_text(self) -> str:
        return self.text(CONTROL_OUT, CONTROL_IN)


class VpcBoundary:
    def __init__(
        self,
        agent: DataPlaneAgent,
        *,
        channel_key: bytes,
        scanner: Scanner | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.agent, self._key, self.scanner, self._clock = agent, channel_key, scanner or Scanner(), clock
        self.log = BoundaryLog()

    def send(self, request: EstimateRequest | ExecuteRequest) -> EstimateResponse | ExecuteResponse:
        kind = "execute" if isinstance(request, ExecuteRequest) else "estimate"
        body = request.model_dump_json()
        issued_at = self._clock()
        envelope = Envelope(
            message_id=request.message_id,
            issued_at=issued_at,
            kind=kind,
            body=body,
            signature=sign(self._key, message_id=request.message_id, issued_at=issued_at, kind=kind, body=body),
        )
        return self._exchange(envelope, EstimateResponse if kind == "estimate" else ExecuteResponse)

    def send_envelope(self, envelope: Envelope, response_model: type[BaseModel]) -> BaseModel:
        """Deliver an already-built (possibly forged or replayed) envelope; used by tests to attack the channel."""
        return self._exchange(envelope, response_model)

    def _exchange(self, envelope: Envelope, response_model: type[BaseModel]):
        outbound = envelope.model_dump_json()
        self._cross(CONTROL_OUT, outbound)
        inbound = self.agent.handle(Envelope.model_validate_json(outbound))
        self._cross(CONTROL_IN, inbound)
        return response_model.model_validate_json(inbound)

    def fetch(self, handle_id: str, bearer_token: str) -> FetchResponse:
        """The client path: rows travel here and nowhere else. The token is the user's, and never reaches the control plane."""
        self.log.add(CLIENT_OUT, handle_id)
        response = self.agent.fetch(handle_id, bearer_token)
        self.log.add(CLIENT_IN, response.model_dump_json())
        return response

    def _cross(self, direction: str, payload: str) -> None:
        self.log.add(direction, payload)
        if len(payload) > MAX_MESSAGE_CHARS:
            self.log.violations.append((direction, 1))
            raise BoundaryViolation(direction, 1)
        hits = self.scanner.hits(payload)
        if hits:
            self.log.violations.append((direction, len(hits)))
            raise BoundaryViolation(direction, len(hits))
