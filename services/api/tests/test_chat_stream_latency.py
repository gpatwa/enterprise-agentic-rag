from __future__ import annotations

import json
import os

import pytest
from fastapi import BackgroundTasks

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


def _ctx(role: str = "admin", tenant_id: str = "tenant-a", user_id: str = "alice"):
    from app.auth.tenant import TenantContext

    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        permissions=[],
    )


class FakeCache:
    async def get_cached_response_with_embedding(self, message, *, tenant_id):
        return "Cached answer.", [0.1, 0.2]


class FakeMemory:
    async def add_message(self, *args, **kwargs):
        return None


class FakeLLM:
    pass


@pytest.mark.asyncio
async def test_cached_chat_stream_emits_latency_lifecycle_events():
    from app.routes.chat import ChatRequest, chat_stream

    response = await chat_stream(
        ChatRequest(message="hello"),
        BackgroundTasks(),
        ctx=_ctx(),
        _rl=None,
        cache=FakeCache(),
        memory=FakeMemory(),
        llm=FakeLLM(),
    )

    events = []
    async for chunk in response.body_iterator:
        events.append(json.loads(chunk))

    assert [event["type"] for event in events] == [
        "stream_start",
        "first_token",
        "answer",
        "stream_done",
    ]
    assert events[1]["source"] == "cache"
    assert events[1]["time_ms"] >= 0
    assert events[2]["content"] == "Cached answer."
    assert events[3]["first_token_ms"] == events[1]["time_ms"]
    assert events[3]["output_chars"] == len("Cached answer.")
