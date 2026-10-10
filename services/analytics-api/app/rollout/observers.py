"""What a rollout can observe (ADS-057). Implementations decide where the numbers come from."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ShadowResult:
    total: int
    agreeing: int

    @property
    def agreement(self) -> float:
        return self.agreeing / self.total if self.total else 0.0


@dataclass(frozen=True)
class CanaryResult:
    requests: int
    errors: int

    @property
    def error_rate(self) -> float:
        return self.errors / self.requests if self.requests else 1.0  # no traffic is not evidence of health


class Observers(Protocol):
    def shadow(self, candidate_text: str, baseline_text: str) -> ShadowResult:
        """Compare what the candidate would decide with what the baseline decides, without executing anything."""

    def canary(self, candidate_text: str, fraction: float) -> CanaryResult:
        """Serve the given fraction of requests with the candidate and report how many went wrong."""

    def monitor(self, released_text: str) -> CanaryResult:
        """Observe a promoted version."""
