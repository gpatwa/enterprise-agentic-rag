"""Pure, redacted telemetry attributes for resolution operations.

This module deliberately accepts only operational summaries.  It has no
exporter or logging dependency; callers may ignore telemetry construction.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

MAX_COUNT = 1_000_000
MAX_MILLISECONDS = 86_400_000.0
MAX_COST_USD = 1_000_000.0
MAX_TEXT_LENGTH = 128
_QUALITY_COUNTERS = frozenset({
    "claims", "supported_claims", "citations", "invalid_citations",
    "abstentions", "fallbacks", "action_proposals", "policy_denials",
})


def _number(value: Any, name: str, maximum: float) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    if not math.isfinite(value) or value < 0 or value > maximum:
        raise ValueError(f"{name} must be finite and between zero and {maximum}")
    return value


def _count(value: Any, name: str) -> int:
    checked = _number(value, name, MAX_COUNT)
    if int(checked) != checked:
        raise ValueError(f"{name} must be an integer")
    return int(checked)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"{name} must be a bounded non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} contains control characters")
    return value


def latency_ms(value: int | float) -> float:
    """Validate a finite, bounded duration in milliseconds."""
    return float(_number(value, "latency_ms", MAX_MILLISECONDS))


def token_counts(*, input_tokens: int, output_tokens: int) -> dict[str, int]:
    """Return bounded token counters; no token content is accepted."""
    return {"input_tokens": _count(input_tokens, "input_tokens"), "output_tokens": _count(output_tokens, "output_tokens")}


def estimated_cost_usd(*, input_tokens: int, output_tokens: int, input_rate: float = 0.0, output_rate: float = 0.0) -> float:
    """Estimate cost from counts and non-negative per-token rates."""
    counts = token_counts(input_tokens=input_tokens, output_tokens=output_tokens)
    in_rate = float(_number(input_rate, "input_rate", MAX_COST_USD))
    out_rate = float(_number(output_rate, "output_rate", MAX_COST_USD))
    cost = counts["input_tokens"] * in_rate + counts["output_tokens"] * out_rate
    return float(_number(cost, "estimated_cost_usd", MAX_COST_USD))


def quality_counters(counters: Mapping[str, int]) -> dict[str, int]:
    """Keep only the fixed, bounded quality-counter vocabulary."""
    if not isinstance(counters, Mapping):
        raise TypeError("counters must be a mapping")
    unknown = set(counters) - _QUALITY_COUNTERS
    if unknown:
        raise ValueError("unknown quality counter")
    return {key: _count(counters.get(key, 0), key) for key in sorted(_QUALITY_COUNTERS) if key in counters}


def build_telemetry(*, latency: int | float, input_tokens: int, output_tokens: int,
                    estimated_cost: int | float, route: str, stage: str,
                    model_version: str, prompt_version: str, policy_version: str,
                    fallback_reason: str | None = None,
                    quality: Mapping[str, int] | None = None) -> dict[str, Any]:
    """Build deterministic, bounded attributes containing no request content."""
    result: dict[str, Any] = {
        "latency_ms": latency_ms(latency),
        **token_counts(input_tokens=input_tokens, output_tokens=output_tokens),
        "estimated_cost_usd": float(_number(estimated_cost, "estimated_cost_usd", MAX_COST_USD)),
        "route": _text(route, "route"), "stage": _text(stage, "stage"),
        "model_version": _text(model_version, "model_version"),
        "prompt_version": _text(prompt_version, "prompt_version"),
        "policy_version": _text(policy_version, "policy_version"),
    }
    if fallback_reason is not None:
        result["fallback_reason"] = _text(fallback_reason, "fallback_reason")
    if quality is not None:
        result.update({f"quality_{key}": value for key, value in quality_counters(quality).items()})
    return {key: result[key] for key in sorted(result)}


def try_build_telemetry(**kwargs: Any) -> dict[str, Any] | None:
    """Best-effort boundary for callers that must never fail on telemetry."""
    try:
        return build_telemetry(**kwargs)
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = ["build_telemetry", "estimated_cost_usd", "latency_ms", "quality_counters", "token_counts", "try_build_telemetry"]
