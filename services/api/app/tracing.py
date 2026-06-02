# services/api/app/tracing.py
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
except ImportError:  # pragma: no cover - only used when optional deps are absent
    trace = None
    Status = None
    StatusCode = None

TRACER_NAME = "compass.api"


class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        return None

    def record_exception(self, exception: Exception) -> None:
        return None

    def set_status(self, status: Any) -> None:
        return None


@contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None, **extra: Any) -> Iterator[Any]:
    """Start a custom span with safe, low-cardinality attributes.

    Keep request bodies, customer text, ticket descriptions, and raw queries out
    of traces. Use lengths, counts, provider/status, tenant/job ids, and outcome
    fields instead.
    """
    if trace is None:
        yield _NoopSpan()
        return

    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(name) as span:
        set_span_attributes(span, attributes, **extra)
        try:
            yield span
        except Exception as exc:
            record_span_error(span, exc)
            raise


def current_span() -> Any:
    if trace is None:
        return _NoopSpan()
    return trace.get_current_span()


def set_span_attributes(span: Any, attributes: dict[str, Any] | None = None, **extra: Any) -> None:
    payload = {**(attributes or {}), **extra}
    for key, value in payload.items():
        safe_value = _safe_attribute_value(value)
        if safe_value is None:
            continue
        try:
            span.set_attribute(key, safe_value)
        except Exception:
            # Tracing must never affect application behavior.
            continue


def add_span_event(span: Any, name: str, attributes: dict[str, Any] | None = None, **extra: Any) -> None:
    payload = {
        key: value
        for key, value in ((attributes or {}) | extra).items()
        if _safe_attribute_value(value) is not None
    }
    payload = {key: _safe_attribute_value(value) for key, value in payload.items()}
    try:
        span.add_event(name, payload)
    except Exception:
        return


def record_span_error(span: Any, exc: Exception) -> None:
    try:
        span.record_exception(exc)
        if Status is not None and StatusCode is not None:
            span.set_status(Status(StatusCode.ERROR, exc.__class__.__name__))
    except Exception:
        return


def _safe_attribute_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int, float)):
        return value
    if isinstance(value, (list, tuple, set)):
        normalized = [str(item) for item in value if item is not None]
        return normalized or None
    return str(value)
