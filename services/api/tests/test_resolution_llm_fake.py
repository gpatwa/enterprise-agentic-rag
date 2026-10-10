import asyncio

import pytest
from tests.fakes.llm import ScriptedLLM


@pytest.mark.asyncio
async def test_scripted_llm_queues_text_json_and_captures_strict_json_mode():
    client = ScriptedLLM("plain response", {"answer": "structured"})

    assert await client.chat_completion(
        [{"role": "user", "content": "one"}], temperature=0.2, json_mode=False
    ) == "plain response"
    assert await client.chat_completion(
        [{"role": "system", "content": "two"}], json_mode=True
    ) == '{"answer": "structured"}'
    assert client.calls[1].json_mode is True
    assert client.calls[1].messages == [{"role": "system", "content": "two"}]


@pytest.mark.asyncio
async def test_scripted_llm_queues_exceptions_and_timeout_is_awaitable():
    client = ScriptedLLM().enqueue_exception(RuntimeError("provider failed")).enqueue_timeout(1)

    with pytest.raises(RuntimeError, match="provider failed"):
        await client.chat_completion([])

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client.chat_completion([], json_mode=True), timeout=0.01)
    assert client.calls[-1].json_mode is True


@pytest.mark.asyncio
async def test_scripted_llm_lifecycle_and_empty_queue_are_deterministic():
    client = ScriptedLLM("ok")
    await client.start()
    await client.close()
    assert client.started and client.closed
    assert await client.chat_completion([]) == "ok"
    with pytest.raises(AssertionError, match="queue is empty"):
        await client.chat_completion([])
