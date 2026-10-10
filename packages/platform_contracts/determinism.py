"""Deterministic controls used by local harness scenarios."""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


class DeterministicBudgetExceeded(RuntimeError):
    """Raised when a scenario exceeds its token or cost budget."""


@dataclass
class DeterministicClock:
    current: datetime

    def __post_init__(self) -> None:
        if self.current.tzinfo is None or self.current.utcoffset() is None:
            raise ValueError("deterministic clock requires a timezone-aware start")

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> datetime:
        if seconds < 0:
            raise ValueError("deterministic clock cannot move backwards")
        self.current += timedelta(seconds=seconds)
        return self.current


@dataclass
class DeterministicIdFactory:
    seed: str
    counters: dict[str, int] = field(default_factory=dict)

    def next(self, namespace: str) -> str:
        counter = self.counters.get(namespace, 0) + 1
        self.counters[namespace] = counter
        value = hashlib.sha256(f"{self.seed}:{namespace}:{counter}".encode()).hexdigest()[:16]
        return f"{namespace}-{value}"


class DeterministicRandom:
    def __init__(self, seed: str):
        self._random = random.Random(seed)

    def randint(self, start: int, end: int) -> int:
        return self._random.randint(start, end)


@dataclass
class TokenCostController:
    max_tokens: int
    max_cost_units: float
    tokens_used: int = 0
    cost_units: float = 0.0

    def consume(self, tokens: int, cost_units: float) -> None:
        if tokens < 0 or cost_units < 0:
            raise ValueError("token and cost consumption cannot be negative")
        if self.tokens_used + tokens > self.max_tokens:
            raise DeterministicBudgetExceeded("token budget exceeded")
        if self.cost_units + cost_units > self.max_cost_units:
            raise DeterministicBudgetExceeded("cost budget exceeded")
        self.tokens_used += tokens
        self.cost_units += cost_units


@dataclass
class DeterministicControls:
    seed: str
    clock: DeterministicClock
    ids: DeterministicIdFactory
    random: DeterministicRandom
    budget: TokenCostController

    @classmethod
    def from_seed(
        cls, seed: str, *, start: datetime | None = None,
        max_tokens: int = 4_000, max_cost_units: float = 100.0,
    ) -> "DeterministicControls":
        return cls(
            seed=seed,
            clock=DeterministicClock(start or datetime(2026, 1, 1, tzinfo=timezone.utc)),
            ids=DeterministicIdFactory(seed), random=DeterministicRandom(seed),
            budget=TokenCostController(max_tokens=max_tokens, max_cost_units=max_cost_units),
        )
