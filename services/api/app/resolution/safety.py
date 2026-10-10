"""Boundaries for untrusted ticket and retrieved evidence text.

These helpers do not identify prompt injection. They make text data explicit,
remove disruptive controls, and keep payloads within deterministic bounds.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

DEFAULT_FIELD_LIMIT = 2_000
DEFAULT_TOTAL_LIMIT = 8_000
_DISALLOWED_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_untrusted_text(value: object) -> str:
    """Return text with disruptive controls removed and whitespace bounded."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = _DISALLOWED_CONTROLS.sub("", text)
    return text.strip()


def bound_untrusted_text(value: object, limit: int = DEFAULT_FIELD_LIMIT) -> str:
    """Clean text and cap it by characters, using an explicit truncation mark."""
    if limit < 1:
        raise ValueError("limit must be positive")
    text = clean_untrusted_text(value)
    if len(text) <= limit:
        return text
    marker = "...[truncated]"
    if limit <= len(marker):
        return marker[:limit]
    return text[: limit - len(marker)] + marker


def format_evidence_text(
    ticket_text: object,
    evidence: Iterable[Mapping[str, object]],
    *,
    field_limit: int = DEFAULT_FIELD_LIMIT,
    total_limit: int = DEFAULT_TOTAL_LIMIT,
) -> str:
    """Format bounded ticket/evidence as quoted data for a model input.

    IDs are copied without normalization so they remain valid citation keys.
    The return value is text only; callers must supply their own system message.
    """
    if field_limit < 1 or total_limit < 1:
        raise ValueError("limits must be positive")

    sections = [
        "<untrusted-resolution-data>",
        "<ticket>",
        bound_untrusted_text(ticket_text, field_limit),
        "</ticket>",
    ]
    for item in evidence:
        document_id = str(item.get("document_id", ""))
        source_id = str(item.get("source_id", ""))
        label = str(item.get("label", ""))
        title = bound_untrusted_text(item.get("title", ""), field_limit)
        text = bound_untrusted_text(item.get("snippet", item.get("text", "")), field_limit)
        sections.extend(
            [
                "<evidence>",
                f"<label>{label}</label>",
                f"<document_id>{document_id}</document_id>",
                f"<source_id>{source_id}</source_id>",
                f"<title>{title}</title>",
                f"<text>{text}</text>",
                "</evidence>",
            ]
        )
    sections.append("</untrusted-resolution-data>")
    result = "\n".join(sections)
    return bound_untrusted_text(result, total_limit)


__all__ = [
    "DEFAULT_FIELD_LIMIT",
    "DEFAULT_TOTAL_LIMIT",
    "bound_untrusted_text",
    "clean_untrusted_text",
    "format_evidence_text",
]
