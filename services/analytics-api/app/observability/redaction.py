"""Redaction for telemetry (ADS-065): tokens, secrets, SQL, addresses, and registered literals never leave as text."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = "[REDACTED]"
MAX_TEXT = 200

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), REDACTED),  # a JWT
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer " + REDACTED),
    # Credentials inside a URL come before the e-mail rule, which would otherwise take the tail of "pw@host" first.
    (re.compile(r"(?i)://[^/\s:@]+:[^@\s]+@"), "://" + REDACTED + "@"),
    (
        re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|credential)s?\b\s*[=:]\s*\S+"),
        r"\1=" + REDACTED,
    ),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (
        re.compile(
            r"(?is)\b(?:select|insert|update|delete|drop|alter|create|truncate|with)\b[^;\n]*?"
            r"\b(?:from|into|table|set|values|as)\b[^;\n]*"
        ),
        "[SQL]",
    ),
)


class Redactor:
    def __init__(self, literals: Iterable[str] = ()) -> None:
        self._literals: set[str] = {value for value in literals if value}

    def register(self, *values: str) -> None:
        self._literals.update(value for value in values if value)

    def text(self, value: str) -> str:
        for literal in sorted(self._literals, key=len, reverse=True):
            value = value.replace(literal, REDACTED)
        for pattern, replacement in _PATTERNS:
            value = pattern.sub(replacement, value)
        return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + "...[truncated]"

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return REDACTED  # structures and objects are never emitted whole

    def mapping(self, values: Mapping[str, Any]) -> dict[str, Any]:
        return {str(key): self.value(item) for key, item in values.items()}
