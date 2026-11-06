"""Adapter that lets the plain ``write(batch)`` indexers be used as Ray Data sinks.

``QdrantIndexer`` and ``Neo4jIndexer`` are plain classes with ``write(batch: list[dict])``. Newer Ray (checked on
2.54.0) has no ``Dataset.write_datasource`` at all: sinks must be ``Datasink`` objects and are written with
``write_datasink``, which hands ``write(blocks, ctx)`` Arrow/pandas blocks, not lists of dicts. This module wraps any
plain sink so it receives ``list[dict]`` rows, and falls back to the old call on a Ray that has no
``write_datasink`` (the fallback is the previous behaviour and is not tested here).
"""

from __future__ import annotations

from typing import Any, Protocol

try:  # Ray is only installed where the pipeline runs
    from ray.data import Datasink as _DatasinkBase
    from ray.data.block import BlockAccessor
except ImportError:  # pragma: no cover - exercised only without Ray
    _DatasinkBase = object  # type: ignore[assignment,misc]
    BlockAccessor = None  # type: ignore[assignment,misc]


class RowSink(Protocol):
    def write(self, batch: list[dict[str, Any]]) -> Any: ...


class RowDatasink(_DatasinkBase):  # type: ignore[misc,valid-type]
    """Passes each non-empty block to ``sink.write`` as a list of row dicts; errors propagate and fail the job."""

    def __init__(self, sink: RowSink) -> None:
        self.sink = sink

    def write(self, blocks: Any, ctx: Any) -> int:
        written = 0
        for block in blocks:
            rows = list(BlockAccessor.for_block(block).iter_rows(public_row_format=True))
            if rows:
                self.sink.write(rows)
                written += len(rows)
        return written


def write_rows(dataset: Any, sink: RowSink) -> None:
    """Write ``dataset`` through ``sink`` on whichever Ray API the installed version offers."""
    if hasattr(dataset, "write_datasink"):
        dataset.write_datasink(RowDatasink(sink))
    else:
        dataset.write_datasource(sink)
