"""Traces, metrics, and structured logs with run correlation (ADS-065).

OpenTelemetry-shaped but dependency-free and in memory: a span has a trace and parent, a layer, timings, and *allow-listed*
attributes only; metrics are counters and histograms with an allow-listed, cardinality-capped label set; logs are JSON lines that
carry the trace and span IDs. Nothing here ever receives a request, a row, SQL, or a token: attributes outside the allow-list
are dropped (and counted), and every string passes the redactor. A run is one trace: the trace ID derives from the run ID, so the
analyze call and every later clarify or review of that run join the same trace.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import secrets
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from app.observability.redaction import Redactor

LAYERS = ("api", "graph", "context", "gateway", "evidence")
ATTRIBUTE_ALLOWLIST = frozenset(
    {
        "op",
        "tool",
        "node_id",
        "status",
        "next_node",
        "outcome",
        "state",
        "error_code",
        "terminal_kind",
        "dialect",
        "row_count",
        "byte_count",
        "truncated",
        "cost_units",
        "chain_seq",
        "validation_status",
        "transport",
        "run_ref",
        "tenant_id",
        "cache_hit",
    }
)
LABEL_ALLOWLIST = frozenset({"op", "tool", "node", "outcome", "error_code", "dialect", "layer", "tenant"})
MAX_LABEL_VALUES = 200


def trace_id_for_run(tenant_id: str, run_id: str) -> str:
    return hashlib.sha256(f"trace:{tenant_id}:{run_id}".encode()).hexdigest()[:32]


def run_ref(run_id: str) -> str:
    """A short, non-reversible handle that correlates telemetry to a run without printing the run ID."""
    return hashlib.sha256(f"run:{run_id}".encode()).hexdigest()[:16]


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    layer: str
    started_at: float
    ended_at: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error_code: str | None = None
    dropped_attributes: int = 0

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.ended_at or self.started_at) - self.started_at)


_current: contextvars.ContextVar[Span | None] = contextvars.ContextVar("analytics_current_span", default=None)


class Tracer:
    def __init__(self, redactor: Redactor, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self.redactor, self._clock = redactor, clock
        self._lock = threading.Lock()
        self.finished: list[Span] = []

    @contextmanager
    def span(self, name: str, layer: str, *, trace_id: str | None = None, **attributes: Any) -> Iterator[Span]:
        parent = _current.get()
        span = Span(
            trace_id=trace_id or (parent.trace_id if parent else secrets.token_hex(16)),
            span_id=secrets.token_hex(8),
            parent_id=parent.span_id if parent else None,
            name=name,
            layer=layer,
            started_at=self._clock(),
        )
        self.annotate(span, **attributes)
        token = _current.set(span)
        try:
            yield span
        except BaseException as exc:
            span.status, span.error_code = "error", type(exc).__name__
            raise
        finally:
            _current.reset(token)
            span.ended_at = self._clock()
            with self._lock:
                self.finished.append(span)

    def annotate(self, span: Span, **attributes: Any) -> None:
        for key, value in attributes.items():
            if key not in ATTRIBUTE_ALLOWLIST or value is None:
                if key not in ATTRIBUTE_ALLOWLIST:
                    span.dropped_attributes += 1
                continue
            span.attributes[key] = self.redactor.value(value)

    @staticmethod
    def current() -> Span | None:
        return _current.get()

    def trace(self, trace_id: str) -> list[Span]:
        with self._lock:
            return [span for span in self.finished if span.trace_id == trace_id]


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(list)
        self._label_values: dict[str, set[str]] = defaultdict(set)
        self.dropped_labels = 0

    def inc(self, name: str, amount: float = 1.0, **labels: Any) -> None:
        with self._lock:
            self._counters[(name, self._labels(labels))] += amount

    def observe(self, name: str, value: float, **labels: Any) -> None:
        with self._lock:
            self._histograms[(name, self._labels(labels))].append(float(value))

    def _labels(self, labels: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        clean: list[tuple[str, str]] = []
        for key, value in sorted(labels.items()):
            if key not in LABEL_ALLOWLIST:
                self.dropped_labels += 1
                continue
            text = str(value)[:64]
            seen = self._label_values[key]
            if text not in seen and len(seen) >= MAX_LABEL_VALUES:
                text = "other"  # cardinality is capped, so a flood of values cannot grow the registry
            else:
                seen.add(text)
            clean.append((key, text))
        return tuple(clean)

    def counter(self, name: str, **labels: Any) -> float:
        with self._lock:
            return self._counters.get((name, self._labels(labels)), 0.0)

    def samples(self, name: str, **labels: Any) -> list[float]:
        with self._lock:
            return list(self._histograms.get((name, self._labels(labels)), []))

    def exposition(self) -> str:
        """Prometheus text format."""
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{name}{_render(labels)} {value:g}")
            for (name, labels), values in sorted(self._histograms.items()):
                lines.append(f"{name}_count{_render(labels)} {len(values)}")
                lines.append(f"{name}_sum{_render(labels)} {sum(values):.6f}")
        return "\n".join(lines) + ("\n" if lines else "")


def _render(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{key}="{value.replace(chr(34), chr(39))}"' for key, value in labels) + "}"


class StructuredLog:
    """JSON-line logs carrying the current trace and span; every field passes the redactor."""

    def __init__(self, redactor: Redactor) -> None:
        self.redactor = redactor
        self._lock = threading.Lock()
        self.lines: list[str] = []

    def emit(self, level: str, event: str, **fields: Any) -> str:
        span = _current.get()
        record = {
            "level": level,
            "event": self.redactor.text(event),
            "trace_id": span.trace_id if span else None,
            "span_id": span.span_id if span else None,
            **{key: value for key, value in self.redactor.mapping(fields).items() if key not in {"level", "event"}},
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with self._lock:
            self.lines.append(line)
        return line


class Observability:
    def __init__(self, redactor: Redactor | None = None, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self.redactor = redactor or Redactor()
        self.tracer = Tracer(self.redactor, clock=clock)
        self.metrics = Metrics()
        self.log = StructuredLog(self.redactor)

    def telemetry_text(self) -> str:
        """Everything this instance would export, as one string (used to prove nothing sensitive is in it)."""
        spans = [
            json.dumps(
                {
                    "trace": s.trace_id,
                    "span": s.span_id,
                    "parent": s.parent_id,
                    "name": s.name,
                    "layer": s.layer,
                    "attrs": s.attributes,
                    "status": s.status,
                    "error": s.error_code,
                },
                sort_keys=True,
                default=str,
            )
            for s in self.tracer.finished
        ]
        return "\n".join([*spans, *self.log.lines, self.metrics.exposition()])
