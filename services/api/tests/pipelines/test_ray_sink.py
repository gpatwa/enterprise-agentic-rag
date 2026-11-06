"""RO-1: the plain write(batch) indexers must work as Ray Data sinks.

The first group needs no Ray. The second runs a real local Ray and is skipped when Ray is not installed.
"""

from __future__ import annotations

import json

import pytest

from pipelines.ingestion.indexing.ray_sink import write_rows


class LegacyDataset:
    """A Ray without write_datasink: only the old call exists."""

    def __init__(self) -> None:
        self.sources: list[object] = []

    def write_datasource(self, sink: object) -> None:
        self.sources.append(sink)


class NewDataset:
    def __init__(self) -> None:
        self.sinks: list[object] = []

    def write_datasink(self, sink: object) -> None:
        self.sinks.append(sink)


class Collect:
    def __init__(self) -> None:
        self.batches: list[list[dict]] = []

    def write(self, batch: list[dict]) -> None:
        self.batches.append(batch)


def test_old_ray_keeps_the_previous_call() -> None:
    dataset, sink = LegacyDataset(), Collect()
    write_rows(dataset, sink)
    assert dataset.sources == [sink]


def test_new_ray_gets_a_datasink_wrapping_the_sink() -> None:
    dataset, sink = NewDataset(), Collect()
    write_rows(dataset, sink)
    assert len(dataset.sinks) == 1 and dataset.sinks[0] is not sink and dataset.sinks[0].sink is sink


try:
    import pyarrow as pa
    import ray  # noqa: F401

    HAS_RAY = True
except ImportError:  # pragma: no cover
    HAS_RAY = False

needs_ray = pytest.mark.skipif(not HAS_RAY, reason="ray and pyarrow are not installed")


@needs_ray
def test_blocks_reach_the_sink_as_lists_of_dicts_and_empty_blocks_are_skipped() -> None:
    from pipelines.ingestion.indexing.ray_sink import RowDatasink

    sink = Collect()
    written = RowDatasink(sink).write(
        [
            pa.table({"id": [1, 2], "text": ["a", "b"]}),
            pa.table({"id": [], "text": []}),
            pa.table({"id": [3], "text": ["c"]}),
        ],
        None,
    )
    assert written == 3
    assert sink.batches == [[{"id": 1, "text": "a"}, {"id": 2, "text": "b"}], [{"id": 3, "text": "c"}]]


@needs_ray
def test_a_failing_sink_fails_the_write() -> None:
    from pipelines.ingestion.indexing.ray_sink import RowDatasink

    class Boom:
        def write(self, batch: list[dict]) -> None:
            raise RuntimeError("index down")

    with pytest.raises(RuntimeError, match="index down"):
        RowDatasink(Boom()).write([pa.table({"id": [1]})], None)


@pytest.fixture(scope="module")
def local_ray():
    import ray as ray_module

    ray_module.init(num_cpus=2, include_dashboard=False, logging_level="ERROR", ignore_reinit_error=True)
    yield ray_module
    ray_module.shutdown()


@needs_ray
def test_a_real_ray_dataset_writes_every_row_through_a_plain_sink(local_ray, tmp_path) -> None:
    import ray.data

    out = tmp_path / "rows"
    out.mkdir()

    class FileSink:
        """Runs in Ray workers, so it records to disk rather than memory."""

        def __init__(self, directory: str) -> None:
            self.directory = directory

        def write(self, batch: list[dict]) -> None:
            import os
            import uuid

            with open(os.path.join(self.directory, uuid.uuid4().hex + ".json"), "w") as handle:
                json.dump(batch, handle)

    write_rows(ray.data.from_items([{"id": i, "text": f"t{i}"} for i in range(25)]), FileSink(str(out)))

    rows = [row for path in out.iterdir() for row in json.loads(path.read_text())]
    assert sorted(row["id"] for row in rows) == list(range(25))
    assert all(isinstance(row, dict) and row["text"] == f"t{row['id']}" for row in rows)
