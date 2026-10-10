import asyncio
import time

import pytest

from app.resolution.shadow import run_shadow


@pytest.mark.asyncio
async def test_returns_primary_and_emits_redacted_shadow_success():
    events = []

    async def primary():
        return {"answer": "primary", "action": "queue"}

    async def shadow():
        return "raw shadow output"

    result = await run_shadow(primary, shadow, enabled=True, callback=events.append,
                              metadata={"tenant": "tenant-a", "question": "raw question"})
    await asyncio.sleep(0)
    assert result["answer"] == "primary"
    assert events[0]["outcome"] == "success"
    assert "question" not in events[0]
    assert "raw shadow output" not in str(events)


@pytest.mark.asyncio
async def test_shadow_failure_and_timeout_are_fail_open():
    events = []

    async def primary():
        return "primary"

    async def failing_shadow():
        raise RuntimeError("private model output")

    assert await run_shadow(primary, failing_shadow, enabled=True, callback=events.append) == "primary"
    await asyncio.sleep(0)
    assert events[-1]["outcome"] == "failure"

    async def slow_shadow():
        await asyncio.sleep(1)

    assert await run_shadow(primary, slow_shadow, enabled=True, callback=events.append,
                            timeout_seconds=0.001) == "primary"
    await asyncio.sleep(0.01)
    assert events[-1]["outcome"] == "timeout"


@pytest.mark.asyncio
async def test_fast_primary_does_not_wait_for_slow_shadow():
    events = []
    shadow_started = asyncio.Event()

    async def primary():
        return "primary"

    async def slow_shadow():
        shadow_started.set()
        await asyncio.sleep(0.05)

    started = time.perf_counter()
    result = await run_shadow(primary, slow_shadow, enabled=True, callback=events.append,
                              timeout_seconds=1)
    elapsed = time.perf_counter() - started

    assert result == "primary"
    assert elapsed < 0.04
    await shadow_started.wait()
    await asyncio.sleep(0.06)
    assert events[-1]["outcome"] == "success"


@pytest.mark.asyncio
async def test_kill_switch_does_not_start_shadow():
    called = False

    async def primary():
        return 7

    async def shadow():
        nonlocal called
        called = True

    assert await run_shadow(primary, shadow, enabled=False) == 7
    assert called is False
