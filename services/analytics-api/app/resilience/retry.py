"""Bounded retry and a circuit breaker for the two external dependencies of a run: the model and the warehouse (M7-H5).

Only transient failures are retried (`TimeoutError`, `ConnectionError` and its subclasses), at most `attempts` times in all, with a
short fixed backoff. A malformed model reply or a SQL error is never retried: it would fail the same way again. The breaker opens after
`failure_threshold` consecutive transient failures and fails fast with `DependencyUnavailable` until `cooldown_seconds` have passed;
then one trial call is let through (half-open). Reads are idempotent, so retrying a warehouse query cannot change data; it can cost a
second read, which the caller sees in its cost and execution counts.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

TRANSIENT: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError)
T = TypeVar("T")


class DependencyUnavailable(ConnectionError):
    """The circuit is open: the dependency failed repeatedly and is not being called for now."""


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 2  # one try plus one retry
    backoff_seconds: float = 0.2

    def __post_init__(self) -> None:
        if not 1 <= self.attempts <= 5 or self.backoff_seconds < 0:
            raise ValueError("retry attempts must be 1..5 and backoff non-negative")


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or cooldown_seconds <= 0:
            raise ValueError("breaker threshold must be >= 1 and cooldown positive")
        self.name, self.failure_threshold, self.cooldown_seconds, self._clock = (
            name,
            failure_threshold,
            cooldown_seconds,
            clock,
        )
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state()

    def _state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "half_open" if self._clock() - self._opened_at >= self.cooldown_seconds else "open"

    def before_call(self) -> None:
        with self._lock:
            if self._state() == "open":
                raise DependencyUnavailable(f"{self.name} circuit is open")

    def record_success(self) -> None:
        with self._lock:
            self._failures, self._opened_at = 0, None

    def record_failure(self) -> None:
        with self._lock:
            if self._state() == "half_open":
                self._opened_at = self._clock()  # the trial failed: open again for a full cooldown
                return
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = self._clock()


def call_with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy = RetryPolicy(),
    breaker: CircuitBreaker | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    last: BaseException | None = None
    for attempt in range(policy.attempts):
        if breaker is not None:
            breaker.before_call()
        try:
            result = fn()
        except TRANSIENT as exc:
            last = exc
            if breaker is not None:
                breaker.record_failure()
            if attempt + 1 < policy.attempts:
                sleep(policy.backoff_seconds)
            continue
        if breaker is not None:
            breaker.record_success()
        return result
    assert last is not None
    raise last


class ResilientModelClient:
    """Wraps a structured-output model client (`complete_json`)."""

    def __init__(
        self,
        inner: Any,
        *,
        policy: RetryPolicy = RetryPolicy(),
        breaker: CircuitBreaker | None = None,
        sleep=time.sleep,
    ) -> None:
        self._inner, self._policy, self._breaker, self._sleep = inner, policy, breaker, sleep

    def complete_json(self, *, prompt: str, schema: dict, max_tokens: int) -> Any:
        return call_with_retry(
            lambda: self._inner.complete_json(prompt=prompt, schema=schema, max_tokens=max_tokens),
            policy=self._policy,
            breaker=self._breaker,
            sleep=self._sleep,
        )


class ResilientGateway:
    """Wraps an execution gateway: `execute` and `estimate` are retried on transient failures; `dialect` passes through."""

    def __init__(
        self,
        inner: Any,
        *,
        policy: RetryPolicy = RetryPolicy(),
        breaker: CircuitBreaker | None = None,
        sleep=time.sleep,
    ) -> None:
        self._inner, self._policy, self._breaker, self._sleep = inner, policy, breaker, sleep
        self.dialect = inner.dialect

    def estimate(self, plan: Any) -> float:
        return call_with_retry(
            lambda: self._inner.estimate(plan), policy=self._policy, breaker=self._breaker, sleep=self._sleep
        )

    def execute(self, plan: Any, **kwargs: Any) -> Any:
        return call_with_retry(
            lambda: self._inner.execute(plan, **kwargs), policy=self._policy, breaker=self._breaker, sleep=self._sleep
        )
