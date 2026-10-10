"""Deterministic cost and model routing policy for resolution query planning."""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar

from app.resolution.models import ConfidenceLevel, SearchPlan, SupportIntent


class ModelRoute(str, Enum):
    CHEAP = "cheap"
    STRONG = "strong"
    DETERMINISTIC = "deterministic"


@dataclass(frozen=True)
class ResolutionBudget:
    max_query_variants: int = 4
    max_input_tokens: int = 2000
    max_output_tokens: int = 500
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        for name in ("max_query_variants", "max_input_tokens", "max_output_tokens"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True)
class RoutingPolicy:
    cheap_model: str = "cheap"
    strong_model: str = "strong"
    kill_switch: bool = False
    cache_ttl_seconds: float = 300.0
    cache_max_entries: int = 256

    def __post_init__(self) -> None:
        if self.cache_ttl_seconds <= 0 or self.cache_max_entries <= 0:
            raise ValueError("cache TTL and size must be positive")


def make_cache_key(tenant_id: str, intent: SupportIntent, *, policy_version: str = "v1") -> str:
    """Return a stable opaque key; identity and original ticket text are absent."""
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id cannot be blank")
    payload = {"tenant": tenant_id.strip(), "intent": intent.model_dump(mode="json"), "policy": policy_version}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"resolution-plan:{digest}"


T = TypeVar("T")


class QueryPlanCache(Generic[T]):
    """Small in-process FIFO cache with deterministic expiry and eviction."""

    def __init__(self, *, ttl_seconds: float = 300.0, max_entries: int = 256, clock: Any = time.monotonic) -> None:
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("cache TTL and size must be positive")
        self.ttl_seconds, self.max_entries, self._clock = ttl_seconds, max_entries, clock
        self._entries: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def _purge(self, now: float) -> None:
        for key, (expires, _) in list(self._entries.items()):
            if expires <= now:
                del self._entries[key]

    def get(self, key: str) -> T | None:
        self._purge(self._clock())
        item = self._entries.get(key)
        return None if item is None else item[1]

    def put(self, key: str, value: T) -> None:
        now = self._clock()
        self._purge(now)
        self._entries.pop(key, None)
        self._entries[key] = (now + self.ttl_seconds, value)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        self._purge(self._clock())
        return len(self._entries)


def choose_route(intent: SupportIntent, *, cached: bool = False, policy: RoutingPolicy | None = None) -> ModelRoute:
    policy = policy or RoutingPolicy()
    if policy.kill_switch:
        return ModelRoute.DETERMINISTIC
    if cached or (intent.confidence == ConfidenceLevel.HIGH and intent.intent.value != "unknown"):
        return ModelRoute.CHEAP
    return ModelRoute.STRONG


def route_query_plan(tenant_id: str, intent: SupportIntent, cache: QueryPlanCache[SearchPlan], *, policy: RoutingPolicy | None = None) -> tuple[ModelRoute, SearchPlan | None]:
    policy = policy or RoutingPolicy()
    key = make_cache_key(tenant_id, intent)
    cached = cache.get(key)
    route = choose_route(intent, cached=cached is not None, policy=policy)
    return route, None if route == ModelRoute.DETERMINISTIC else cached


__all__ = ["ModelRoute", "ResolutionBudget", "RoutingPolicy", "QueryPlanCache", "make_cache_key", "choose_route", "route_query_plan"]
