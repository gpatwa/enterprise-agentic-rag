"""Prometheus metrics for the OpenSearch chat-retrieval canary (docs/RAG_OPENSEARCH_CANARY_PLAN.md).

Labels are deliberately low-cardinality: no tenant, query or document identifiers. ``role`` says why a backend was
called: ``served`` (its answer went to the user), ``shadow`` (compared only) or ``fallback`` (Qdrant after an OpenSearch
failure). Exposed on the existing ``/health/metrics`` endpoint through the default prometheus_client registry.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

LATENCY_BUCKETS = (0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.5, 5.0)

RETRIEVAL_REQUESTS = Counter(
    "rag_retrieval_requests_total",
    "Chunk-retrieval calls per backend, role and outcome (ok, error, timeout).",
    ["backend", "role", "outcome"],
)
RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_latency_seconds",
    "Chunk-retrieval latency per backend and role (excludes the shared query embedding).",
    ["backend", "role"],
    buckets=LATENCY_BUCKETS,
)
SHADOW_REQUESTS = Counter(
    "rag_shadow_requests_total",
    "Shadow comparisons: compared (both answered) or opensearch_error.",
    ["result"],
)
SHADOW_OVERLAP = Histogram(
    "rag_shadow_overlap_ratio",
    "Share of Qdrant's chunks (by text) that OpenSearch also returned.",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
SHADOW_EMPTY_MISMATCH = Counter(
    "rag_shadow_empty_mismatch_total",
    "Shadow comparisons where Qdrant returned chunks and OpenSearch returned none.",
)
CROSS_TENANT_DROPPED = Counter(
    "rag_retrieval_cross_tenant_dropped_total",
    "OpenSearch results discarded because they belonged to another tenant. Any increase is a stop-the-rollout event.",
)


def outcome_of(result: object) -> str:
    """ok for a value, timeout for a timeout, error for any other exception."""
    if isinstance(result, TimeoutError):  # asyncio.TimeoutError is TimeoutError on Python 3.11+
        return "timeout"
    return "error" if isinstance(result, BaseException) else "ok"


def record_call(backend: str, role: str, result: object, seconds: float) -> None:
    RETRIEVAL_REQUESTS.labels(backend, role, outcome_of(result)).inc()
    RETRIEVAL_LATENCY.labels(backend, role).observe(seconds)


def record_shadow(primary: list, shadow: object) -> None:
    """Record one shadow comparison; ``shadow`` is OpenSearch's list or the exception it raised."""
    if isinstance(shadow, BaseException):
        SHADOW_REQUESTS.labels("opensearch_error").inc()
        return
    SHADOW_REQUESTS.labels("compared").inc()
    SHADOW_OVERLAP.observe(len(set(primary) & set(shadow)) / max(len(primary), 1))
    if primary and not shadow:
        SHADOW_EMPTY_MISMATCH.inc()
