"""A synchronous structured-output client for the intent node (Azure OpenAI or any OpenAI-compatible endpoint).

The graph's intent node calls `complete_json(prompt=..., schema=..., max_tokens=...)` and validates the reply itself, so this client
only asks for a JSON object and returns the parsed object (or the raw text, which the node rejects as malformed). Timeouts and
connection failures surface as `TimeoutError` / `ConnectionError` so `ResilientModelClient` can retry them once.
"""

from __future__ import annotations

import json
from typing import Any


class OpenAIStructuredClient:
    def __init__(
        self, client: Any, *, model: str, timeout_seconds: float = 30.0, reasoning_effort: str | None = None
    ) -> None:
        self._client, self._model, self._timeout = client, model, timeout_seconds
        self._reasoning_effort = reasoning_effort or None

    @classmethod
    def azure(
        cls,
        *,
        endpoint: str,
        api_key: str,
        api_version: str,
        deployment: str,
        timeout_seconds: float = 30.0,
        reasoning_effort: str | None = None,
    ):
        from openai import AzureOpenAI

        return cls(
            AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version),
            model=deployment,
            timeout_seconds=timeout_seconds,
            reasoning_effort=reasoning_effort,
        )

    @classmethod
    def openai_compatible(cls, *, api_key: str, model: str, base_url: str | None = None, timeout_seconds: float = 30.0):
        from openai import OpenAI

        return cls(OpenAI(api_key=api_key, base_url=base_url), model=model, timeout_seconds=timeout_seconds)

    def complete_json(self, *, prompt: str, schema: dict, max_tokens: int) -> Any:
        import openai

        # Reasoning models reject temperature/max_tokens and spend completion tokens on thinking, so give them headroom.
        sampling: dict[str, Any] = (
            {"max_completion_tokens": max_tokens + 4000, "reasoning_effort": self._reasoning_effort}
            if self._reasoning_effort
            else {"max_tokens": max_tokens, "temperature": 0}
        )
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "Reply with one JSON object that follows this JSON schema: " + json.dumps(schema),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                timeout=self._timeout,
                **sampling,
            )
        except openai.APITimeoutError as exc:
            raise TimeoutError("model timed out") from exc
        except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as exc:
            raise ConnectionError(type(exc).__name__) from exc
        text = response.choices[0].message.content or ""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text  # the intent node treats unparseable output as malformed; it is never retried
