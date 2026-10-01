"""Read-only execution gateway contract shared by the SQL dialect adapters."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol


class ExecutionError(RuntimeError):
    """Base class; subclasses carry a stable code and never echo SQL or values."""

    code = "execution_failed"


class QueryRejected(ExecutionError):
    code = "query_rejected"


class DialectMismatch(ExecutionError):
    code = "dialect_mismatch"


class CostLimitExceeded(ExecutionError):
    code = "cost_limit_exceeded"


class ExecutionTimeout(ExecutionError):
    code = "execution_timeout"


class ExecutionCancelled(ExecutionError):
    code = "execution_cancelled"


@dataclass(frozen=True)
class ExecutionLimits:
    timeout_seconds: float = 30.0
    max_rows: int = 10_000
    max_bytes: int = 5_000_000
    max_cost_units: float = 1_000_000.0

    def __post_init__(self) -> None:
        if min(self.timeout_seconds, self.max_rows, self.max_bytes, self.max_cost_units) <= 0:
            raise ValueError("execution limits must be positive")


TruncationReason = Literal["max_rows", "max_bytes"]


@dataclass(frozen=True)
class ExecutionResult:
    dialect: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    byte_count: int
    truncated: bool = False
    truncation_reason: TruncationReason | None = None
    estimated_cost_units: float = 0.0
    elapsed_ms: int = 0

    @property
    def row_count(self) -> int:
        return len(self.rows)


class CancellationToken:
    """Thread-safe cancel signal; gateways register a hook that interrupts the driver."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._hook: Callable[[], None] | None = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        with self._lock:
            self._event.set()
            hook = self._hook
        if hook:
            hook()

    def bind(self, hook: Callable[[], None]) -> None:
        with self._lock:
            self._hook = hook
            cancelled = self._event.is_set()
        if cancelled:
            hook()

    def unbind(self) -> None:
        with self._lock:
            self._hook = None


class ExecutionGateway(Protocol):
    dialect: str

    def estimate(self, plan: Any) -> float: ...

    def execute(
        self,
        plan: Any,
        *,
        limits: ExecutionLimits,
        cancellation: CancellationToken | None = None,
    ) -> ExecutionResult: ...


@dataclass
class ResultAccumulator:
    """Apply row and byte caps while rows stream in; stops at the first breached cap."""

    limits: ExecutionLimits
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    byte_count: int = 0
    truncation_reason: TruncationReason | None = None

    def add(self, row: tuple[Any, ...]) -> bool:
        """Return False once the result is full and no more rows should be read."""
        if len(self.rows) >= self.limits.max_rows:
            self.truncation_reason = "max_rows"
            return False
        size = _row_bytes(row)
        if self.byte_count + size > self.limits.max_bytes:
            self.truncation_reason = "max_bytes"
            return False
        self.rows.append(row)
        self.byte_count += size
        return True


def _row_bytes(row: tuple[Any, ...]) -> int:
    return sum(len(str(value).encode("utf-8", "replace")) + 1 for value in row)
