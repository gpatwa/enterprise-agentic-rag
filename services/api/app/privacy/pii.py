# services/api/app/privacy/pii.py
"""
PII detection + redaction.

Lightweight, dependency-free regex detector. Catches the common high-risk
classes (email, US SSN, phone, credit card, IP). Not a substitute for a
purpose-built PII service like Presidio for high-stakes use; designed to be
swappable.

The redactor returns a string with each match replaced by a deterministic
placeholder (`[EMAIL]`, `[SSN]`, etc.) and a list of categories that fired.
"""
from __future__ import annotations

import re
from typing import Iterable

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Email
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # US SSN — must be xxx-xx-xxxx (3-2-4)
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # Credit card (broad — Luhn would be stricter; flag conservatively)
    ("CC", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    # E.164-ish phone
    ("PHONE", re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")),
    # IPv4
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def detect(text: str) -> list[str]:
    """Return distinct categories that matched, in detection order."""
    if not text:
        return []
    found: list[str] = []
    for label, pat in _PATTERNS:
        if pat.search(text):
            if label not in found:
                found.append(label)
    return found


def contains_pii(text: str) -> bool:
    return bool(detect(text))


def redact(text: str, categories: Iterable[str] | None = None) -> tuple[str, list[str]]:
    """
    Replace matches with `[CATEGORY]` placeholders.

    Args:
        text: input string
        categories: optional whitelist of categories to redact (default: all)
    Returns:
        (redacted_text, categories_redacted)
    """
    if not text:
        return text, []

    allow = set(categories) if categories is not None else None
    redacted = text
    fired: list[str] = []

    for label, pat in _PATTERNS:
        if allow is not None and label not in allow:
            continue
        new = pat.sub(f"[{label}]", redacted)
        if new != redacted:
            fired.append(label)
            redacted = new

    return redacted, fired
