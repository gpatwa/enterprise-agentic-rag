from __future__ import annotations

import asyncio
from typing import Any


class OpenSearchError(RuntimeError):
    """Stable, provider-neutral error envelope for OpenSearch operations."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        operation: str,
        status_code: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.operation = operation
        self.status_code = status_code
        self.cause = cause


def normalize_opensearch_exception(
    error: BaseException,
    *,
    operation: str = "operation",
) -> OpenSearchError:
    """Map client-specific failures to deterministic codes and retry policy."""
    if isinstance(error, OpenSearchError):
        return error

    status_code = _status_code(error)
    class_name = type(error).__name__.lower()
    message = str(error).lower()
    error_text = _error_text(error)
    searchable = f"{class_name} {message} {error_text}"

    if _is_timeout(error, searchable):
        return _normalized("timeout", True, operation, status_code, error)
    if status_code in {401, 403} or _contains_any(searchable, "authentication", "unauthorized", "forbidden", "not authorized"):
        return _normalized("auth", False, operation, status_code, error)
    if status_code == 429 or _contains_any(searchable, "throttl", "too many requests", "es_rejected_execution"):
        return _normalized("throttled", True, operation, status_code, error)
    if _contains_any(searchable, "mapping", "mapper_parsing", "strict_dynamic", "knn_vector", "dimension mismatch"):
        return _normalized("mapping", False, operation, status_code, error)
    if status_code in {502, 503, 504} or isinstance(error, (ConnectionError, OSError)) or _contains_any(
        searchable,
        "unavailable",
        "connection refused",
        "connection reset",
        "no living connections",
        "node not connected",
    ):
        return _normalized("unavailable", True, operation, status_code, error)

    return _normalized("unknown", False, operation, status_code, error)


def _normalized(
    code: str,
    retryable: bool,
    operation: str,
    status_code: int | None,
    cause: BaseException,
) -> OpenSearchError:
    suffix = f" (status {status_code})" if status_code is not None else ""
    return OpenSearchError(
        code=code,
        message=f"OpenSearch {operation} failed: {code}{suffix}",
        retryable=retryable,
        operation=operation,
        status_code=status_code,
        cause=cause,
    )


def _status_code(error: BaseException) -> int | None:
    candidates: list[Any] = [error, getattr(error, "meta", None), getattr(error, "info", None)]
    for candidate in candidates:
        if isinstance(candidate, dict):
            value = candidate.get("status_code", candidate.get("status"))
        else:
            value = getattr(candidate, "status_code", getattr(candidate, "status", None))
        if isinstance(value, int):
            return value
    return None


def _error_text(error: BaseException) -> str:
    info = getattr(error, "info", None)
    if isinstance(info, dict):
        nested = info.get("error")
        if isinstance(nested, dict):
            return " ".join(str(nested.get(key, "")) for key in ("type", "reason")).lower()
        if nested:
            return str(nested).lower()
    return ""


def _is_timeout(error: BaseException, searchable: str) -> bool:
    return isinstance(error, (TimeoutError, asyncio.TimeoutError)) or _contains_any(
        searchable,
        "timeout",
        "timed out",
        "connectiontimeout",
    )


def _contains_any(value: str, *needles: str) -> bool:
    return any(needle in value for needle in needles)
