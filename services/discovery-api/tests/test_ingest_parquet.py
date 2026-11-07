"""Parquet input for the product ingest. These run only where pyarrow is importable; it is not a dependency of
this service (see docs/DISCOVERY_INGESTION_RUNBOOK.md), so a normal install skips the whole module."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from app.ingest import (  # noqa: E402
    IngestError,
    ProductProvenance,
    ingest,
    pipeline,  # noqa: E402
)

NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)
PROVENANCE = ProductProvenance(dataset="fixture", dataset_version="parquet-1", citation="synthetic", synthetic=True)
PRODUCT_COLUMNS = [
    "product_id",
    "product_locale",
    "product_title",
    "product_description",
    "product_bullet_point",
    "product_brand",
    "product_color",
]


def _products(n: int = 60) -> dict[str, list[object]]:
    ids = [f"P{i:04d}" for i in range(n)]
    return {
        "product_id": ids,
        "product_locale": ["us"] * n,
        "product_title": [f"Widget {pid}" for pid in ids],
        "product_description": ["A widget"] * n,
        "product_bullet_point": [None if i % 3 == 0 else "durable" for i in range(n)],  # ESCI has nulls
        "product_brand": [None if i % 4 == 0 else "Acme" for i in range(n)],
        "product_color": ["red"] * n,
    }


def _examples(ids: list[object], small: list[object], dtype: object) -> dict[str, object]:
    n = len(ids)
    return {
        "example_id": pa.array(range(n), pa.int64()),
        "query": ["q"] * n,
        "query_id": pa.array([1] * n, pa.int64()),
        "product_id": ids,
        "product_locale": ["us"] * n,
        "esci_label": ["E"] * n,
        "small_version": pa.array(small, dtype),
    }


def _write(path: Path, data: dict[str, object], *, row_group_size: int | None = None) -> Path:
    pq.write_table(pa.table(data), path, row_group_size=row_group_size)
    return path


def _csv_twin(tmp_path: Path, products: dict[str, list[object]], ids: list[object]) -> tuple[Path, Path]:
    p = tmp_path / "products.csv"
    with p.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PRODUCT_COLUMNS)
        for row in zip(*(products[c] for c in PRODUCT_COLUMNS)):
            writer.writerow(["" if v is None else v for v in row])
    e = tmp_path / "examples.csv"
    with e.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["example_id", "query", "query_id", "product_id", "product_locale", "esci_label", "small_version"]
        )
        for n, pid in enumerate(ids):
            writer.writerow([n, "q", 1, pid, "us", "E", 1])
    return p, e


def test_parquet_gives_the_same_subset_as_the_equivalent_csv(tmp_path: Path) -> None:
    products = _products()
    ids = products["product_id"]
    parquet_products = _write(tmp_path / "products.parquet", products, row_group_size=7)
    parquet_examples = _write(tmp_path / "examples.parquet", _examples(ids, [1] * len(ids), pa.int64()))
    csv_products, csv_examples = _csv_twin(tmp_path, products, ids)
    from_parquet = ingest(parquet_products, parquet_examples, provenance=PROVENANCE, limit=20, now=NOW)
    from_csv = ingest(csv_products, csv_examples, provenance=PROVENANCE, limit=20, now=NOW)
    assert from_parquet.manifest.selected == 20
    assert from_parquet.manifest.subset_checksum == from_csv.manifest.subset_checksum
    assert from_parquet.records == from_csv.records
    assert any(r.brand == "" or r.bullets == "" for r in from_parquet.records), "null cells must arrive as empty"


def test_flag_column_stored_as_float_with_nulls_still_selects_products(tmp_path: Path) -> None:
    # Pandas writes an int flag column with nulls as float64, so ``1`` arrives as ``1.0``. Comparing the string
    # "1.0" to "1" would silently judge nothing and build an empty subset.
    products = _products(10)
    ids = products["product_id"]
    small = [1.0, 1.0, None, 0.0, 1.0, 1.0, float("nan"), 1.0, 0.0, 1.0]
    p = _write(tmp_path / "products.parquet", products)
    e = _write(tmp_path / "examples.parquet", _examples(ids, small, pa.float64()))
    result = ingest(p, e, provenance=PROVENANCE, now=NOW)
    assert sorted(r.product_id for r in result.records) == ["P0000", "P0001", "P0004", "P0005", "P0007", "P0009"]


def test_boolean_flag_column_is_read(tmp_path: Path) -> None:
    products = _products(4)
    ids = products["product_id"]
    p = _write(tmp_path / "products.parquet", products)
    e = _write(tmp_path / "examples.parquet", _examples(ids, [True, False, True, False], pa.bool_()))
    assert sorted(r.product_id for r in ingest(p, e, provenance=PROVENANCE, now=NOW).records) == ["P0000", "P0002"]


def test_rows_stream_in_batches_and_only_requested_columns_are_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path / "products.parquet", _products(25), row_group_size=10)
    monkeypatch.setattr(pipeline, "PARQUET_BATCH_ROWS", 4)
    seen = list(pipeline.read_rows(path, ("product_id",), ("product_id", "product_title")))
    assert len(seen) == 25
    assert set(seen[0]) == {"product_id", "product_title"}


def test_missing_columns_in_a_parquet_file_fail_loudly(tmp_path: Path) -> None:
    products = _products(3)
    products.pop("product_locale")
    p = _write(tmp_path / "products.parquet", products)
    e = _write(tmp_path / "examples.parquet", _examples(products["product_id"], [1, 1, 1], pa.int64()))
    with pytest.raises(IngestError, match="missing columns product_locale"):
        ingest(p, e, provenance=PROVENANCE, now=NOW)


def test_an_unreadable_parquet_file_is_an_ingest_error_not_a_traceback(tmp_path: Path) -> None:
    bad = tmp_path / "products.parquet"
    bad.write_bytes(b"this is not parquet")
    e = _write(tmp_path / "examples.parquet", _examples(["A"], [1], pa.int64()))
    with pytest.raises(IngestError, match="unreadable parquet"):
        ingest(bad, e, provenance=PROVENANCE, now=NOW)


def test_parquet_rows_over_the_field_limits_are_quarantined(tmp_path: Path) -> None:
    products = _products(3)
    products["product_description"][1] = "d" * 20_001
    p = _write(tmp_path / "products.parquet", products)
    e = _write(tmp_path / "examples.parquet", _examples(products["product_id"], [1, 1, 1], pa.int64()))
    result = ingest(p, e, provenance=PROVENANCE, now=NOW)
    assert result.manifest.selected == 2
    assert result.manifest.quarantined["field_too_long"] == 1
    assert "ddd" not in json.dumps([q.model_dump() for q in result.quarantine])


def test_without_pyarrow_a_parquet_path_names_the_remedy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ImportError("blocked for the test")
        return real_import(name, *args, **kwargs)

    path = tmp_path / "products.parquet"
    path.write_bytes(b"x")
    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(IngestError, match="needs pyarrow"):
        list(pipeline.read_rows(path, ("product_id",)))
