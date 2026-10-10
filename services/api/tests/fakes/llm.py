"""Deterministic scripted LLM client for resolution tests."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMCall:
    messages: list[dict[str, Any]]
    temperature: float
    json_mode: bool


class ScriptedLLM:
    """An offline LLMClient whose responses are consumed in FIFO order."""

    def __init__(self, *responses: Any) -> None:
        self._responses: list[tuple[str, Any]] = []
        self.calls: list[LLMCall] = []
        self.started = False
        self.closed = False
        for response in responses:
            self.enqueue(response)

    def enqueue(self, response: Any) -> "ScriptedLLM":
        """Queue text, JSON-compatible values, exceptions, or awaitables."""
        if isinstance(response, BaseException):
            self._responses.append(("exception", response))
        elif isinstance(response, str):
            self._responses.append(("text", response))
        else:
            self._responses.append(("json", response))
        return self

    def enqueue_text(self, response: str) -> "ScriptedLLM":
        self._responses.append(("text", response))
        return self

    def enqueue_json(self, response: Any) -> "ScriptedLLM":
        self._responses.append(("json", response))
        return self

    def enqueue_exception(self, error: BaseException) -> "ScriptedLLM":
        self._responses.append(("exception", error))
        return self

    def enqueue_timeout(self, seconds: float = 1.0) -> "ScriptedLLM":
        self._responses.append(("timeout", seconds))
        return self

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        self.calls.append(LLMCall(list(messages), temperature, json_mode))
        if not self._responses:
            raise AssertionError("ScriptedLLM response queue is empty")
        kind, value = self._responses.pop(0)
        if kind == "exception":
            raise value
        if kind == "timeout":
            await asyncio.sleep(value)
            raise AssertionError("ScriptedLLM timeout response completed unexpectedly")
        if kind == "json":
            return json.dumps(value, sort_keys=True)
        return value


FakeLLMClient = ScriptedLLM
