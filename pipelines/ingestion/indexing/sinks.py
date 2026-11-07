"""Chooses which vector sinks a job writes to, from ``INGEST_VECTOR_SINKS`` (default ``qdrant``)."""

from __future__ import annotations

from typing import Any, Mapping

KNOWN = ("qdrant", "opensearch")


def parse_sink_names(environ: Mapping[str, str]) -> list[str]:
    raw = environ.get("INGEST_VECTOR_SINKS", "qdrant")
    names = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not names:
        raise ValueError("INGEST_VECTOR_SINKS is empty")
    unknown = [name for name in names if name not in KNOWN]
    if unknown:
        raise ValueError(f"unknown vector sink(s) {unknown}; choose from {list(KNOWN)}")
    return list(dict.fromkeys(names))


def build_vector_sinks(environ: Mapping[str, str]) -> list[Any]:
    """Build every sink before any work starts, so a bad setting fails the job immediately."""
    names = parse_sink_names(environ)
    if "opensearch" not in names:
        # A sweep flag with no OpenSearch sink is a mistake, not a no-op.
        from pipelines.ingestion.indexing.opensearch import parse_sweep_flag

        if parse_sweep_flag(environ):
            raise ValueError("INGEST_OPENSEARCH_SWEEP is on but opensearch is not in INGEST_VECTOR_SINKS")
    sinks: list[Any] = []
    for name in names:
        if name == "qdrant":
            from pipelines.ingestion.indexing.qdrant import QdrantIndexer

            sinks.append(QdrantIndexer())
        else:
            from pipelines.ingestion.indexing.opensearch import OpenSearchIndexer

            sinks.append(OpenSearchIndexer())
    return sinks


def finalize_sinks(sinks: list[Any]) -> list[Any]:
    """Run each sink's optional ``finalize`` (for example the stale-chunk sweep). Call after every write succeeded."""
    reports = []
    for sink in sinks:
        finalize = getattr(sink, "finalize", None)
        report = finalize() if finalize else None
        if report is not None:
            reports.append(report)
    return reports
