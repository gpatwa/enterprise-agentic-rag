"""A deterministic load simulator for the quota manager (ADS-066; reused by the ADS-076 load evaluation).

Arrivals are scripted `(time, tenant, hold_seconds, cost_units)`; completions are scheduled when a request is admitted. The clock
is a settable fake, so the same script always gives the same result. This exercises admission and accounting, not real latency.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.quotas.manager import QuotaManager


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def set(self, moment: datetime) -> None:
        self.now = moment


@dataclass
class SimulationResult:
    admitted: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    denied: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    peak_in_flight: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cost: dict[str, float] = field(default_factory=lambda: defaultdict(float))


def simulate(
    manager: QuotaManager,
    clock: FakeClock,
    arrivals: list[tuple[float, str, float, float]],
    *,
    start: datetime | None = None,
) -> SimulationResult:
    origin = start or clock.now
    result = SimulationResult()
    completions: list[tuple[float, int, str, float]] = []
    sequence = 0

    def drain(until: float) -> None:
        while completions and completions[0][0] <= until:
            when, _, tenant, cost = heapq.heappop(completions)
            clock.set(origin + timedelta(seconds=when))
            manager.finish(tenant, run_ref=f"sim-{when}-{tenant}-{_}", cost_units=cost, purpose="analytics")
            result.cost[tenant] += cost

    for at, tenant, hold, cost in sorted(arrivals):
        drain(at)
        clock.set(origin + timedelta(seconds=at))
        admission = manager.admit(tenant)
        if admission.allowed:
            result.admitted[tenant] += 1
            sequence += 1
            heapq.heappush(completions, (at + hold, sequence, tenant, cost))
            result.peak_in_flight[tenant] = max(result.peak_in_flight[tenant], manager.usage(tenant).in_flight)
        else:
            result.denied[tenant][admission.code] += 1
    drain(float("inf"))
    return result
