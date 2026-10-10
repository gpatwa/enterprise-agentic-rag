"""Local, fail-open shadow execution for resolution experiments."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.config import settings
from app.resolution.telemetry import try_build_telemetry

SHADOW_TIMEOUT_SECONDS = 1.0
MAX_RESULT_METADATA = 8
_SAFE_METADATA_KEYS = frozenset({"result_count", "confidence", "citation_count", "next_action"})
ShadowCallback = Callable[[Mapping[str, Any]], Any]


def _metadata(value: Mapping[str, Any] | None) -> dict[str, str]:
    """Accept only bounded labels; never inspect or retain resolver results."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key in sorted(value):
        if len(result) >= MAX_RESULT_METADATA:
            break
        if key in _SAFE_METADATA_KEYS and isinstance(value[key], str):
            item = value[key]
            if 0 < len(item) <= 64 and all(ord(char) >= 32 and ord(char) != 127 for char in item):
                result[key] = item
    return result


def _consume_task(task: asyncio.Task[Any]) -> None:
    """Retrieve a worker exception so the event loop never reports it as orphaned."""
    try:
        task.exception()
    except asyncio.CancelledError:
        pass


async def _execute_shadow(
    shadow: Callable[[], Awaitable[Any]],
    *,
    callback: ShadowCallback | None,
    metadata: Mapping[str, Any] | None,
    timeout_seconds: float,
    started: float,
) -> None:
    outcome = "success"
    try:
        await asyncio.wait_for(shadow(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        outcome = "timeout"
    except asyncio.CancelledError:
        outcome = "cancelled"
    except Exception:
        outcome = "failure"
    finally:
        attrs = try_build_telemetry(
            latency=(time.perf_counter() - started) * 1000,
            input_tokens=0,
            output_tokens=0,
            estimated_cost=0,
            route="shadow",
            stage="resolution_shadow",
            model_version="unknown",
            prompt_version="unknown",
            policy_version="unknown",
            fallback_reason=None if outcome == "success" else outcome,
            quality={"fallbacks": int(outcome != "success")},
        )
        if callback is not None and attrs is not None:
            try:
                callback({**attrs, **_metadata(metadata), "outcome": outcome})
            except BaseException:
                pass


async def run_shadow(
    primary: Callable[[], Awaitable[Any]],
    shadow: Callable[[], Awaitable[Any]],
    *,
    callback: ShadowCallback | None = None,
    metadata: Mapping[str, Any] | None = None,
    enabled: bool | None = None,
    timeout_seconds: float = SHADOW_TIMEOUT_SECONDS,
) -> Any:
    """Return the primary result while best-effort executing an isolated shadow."""
    if enabled is None:
        enabled = settings.RESOLUTION_SHADOW_ENABLED
    if not enabled:
        return await primary()

    shadow_task = asyncio.create_task(
        _execute_shadow(
            shadow,
            callback=callback,
            metadata=metadata,
            timeout_seconds=timeout_seconds,
            started=time.perf_counter(),
        )
    )
    shadow_task.add_done_callback(_consume_task)
    return await primary()


__all__ = ["run_shadow"]
