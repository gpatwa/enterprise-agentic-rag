"""Deterministic query cleanup and cheap support-intent routing."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUERY_LENGTH = 4000

_WHITESPACE = re.compile(r"\s+")
_ERROR_CODE = re.compile(
    r"\b(?:ERR|ERROR)[-_ ]?[A-Z0-9]+(?:[-_][A-Z0-9]+)*\b|\bE[-_ ]?\d{3,8}\b",
    re.IGNORECASE,
)
_HTTP_ERROR = re.compile(r"\bHTTP\s+[45]\d{2}\b|\b[45]\d{2}\b", re.IGNORECASE)
_VERSION = re.compile(r"\bv?\d+(?:(?:\.\d+){1,3})(?:[-+][0-9A-Za-z.-]+)?\b|\bv\d+\b")
_QUOTED = re.compile(r"(['\"])(?P<value>[^'\"\r\n]{1,256})\1")


class QueryFastPath(BaseModel):
    """The normalized ticket and the deterministic decision before an LLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    obvious_route: str | None = Field(default=None, max_length=32)
    llm_required: bool

    @field_validator("query")
    @classmethod
    def _query_is_normalized(cls, value: str) -> str:
        normalized = _normalize(value)
        if not normalized:
            raise ValueError("query cannot be blank")
        return normalized


def _normalize(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("query must be a string")
    if len(value) > MAX_QUERY_LENGTH:
        raise ValueError(f"query exceeds maximum length of {MAX_QUERY_LENGTH}")
    # Treat control characters as separators, while retaining all printable
    # identifier, version, and quoted-phrase characters exactly.
    cleaned = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in value)
    return _WHITESPACE.sub(" ", cleaned).strip()


def normalize_ticket_query(ticket: str) -> QueryFastPath:
    """Normalize a bounded ticket and select only unambiguous fast paths."""

    query = _normalize(ticket)
    if not query:
        raise ValueError("query cannot be blank")

    folded = query.casefold()
    if _ERROR_CODE.search(query) or _HTTP_ERROR.search(query):
        route = "exact_error"
    elif re.search(r"\b(?:how do i|how to|steps to|instructions for|configure|configuration|setup|set up)\b", folded):
        route = "how_to"
    elif re.search(r"\b(?:permission|permissions|access|login|log in|sso|sign in|unauthorized|forbidden)\b", folded):
        route = "access"
    elif re.search(r"\b(?:invoice|invoicing|billing|bill|charged|charge|refund|payment)\b", folded):
        route = "billing"
    elif _VERSION.search(query) and re.search(r"\b(?:version|release|upgrade|downgrade)\b", folded):
        route = "version"
    else:
        route = None

    return QueryFastPath(query=query, obvious_route=route, llm_required=route is None)


normalize_query = normalize_ticket_query
