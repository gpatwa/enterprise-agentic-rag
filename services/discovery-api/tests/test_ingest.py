"""Ingestion of an ESCI-shaped product subset, on synthetic fixtures built in a temp directory."""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.ingest import IngestError, ProductProvenance, ingest, verify_subset, write_subset
from app.ingest.__main__ import main as cli_main

NOW = datetime(2026, 11, 3, tzinfo=timezone.utc)
PROVENANCE = ProductProvenance(dataset="fixture", dataset_version="test-1", citation="synthetic", synthetic=True)
PRODUCT_FIELDS = [
    "product_id",
    "product_locale",
    "product_title",
    "product_description",
    "product_bullet_point",
    "product_brand",
    "product_color",
]
EXAMPLE_FIELDS = ["example_id", "query", "query_id", "product_id", "product_locale", "esci_label", "small_version"]


def _product(pid: str, **over: str) -> dict[str, str]:
    row = {
        "product_id": pid,
        "product_locale": "us",
        "product_title": f"Widget {pid}",
        "product_description": "A widget",
        "product_bullet_point": "durable",
        "product_brand": "Acme",
        "product_color": "red",
    }
    row.update(over)
    return row


def _write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _example(pid: str, locale: str = "us", small: str = "1") -> dict[str, str]:
    return {
        "example_id": f"e-{pid}",
        "query": "q",
        "query_id": "1",
        "product_id": pid,
        "product_locale": locale,
        "esci_label": "E",
        "small_version": small,
    }


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    ids = [f"P{n:03d}" for n in range(40)]
    products = _write(tmp_path / "products.csv", PRODUCT_FIELDS, [_product(pid) for pid in ids])
    examples = _write(tmp_path / "examples.csv", EXAMPLE_FIELDS, [_example(pid) for pid in ids])
    return products, examples


def test_limit_and_counts(files: tuple[Path, Path]) -> None:
    result = ingest(*files, provenance=PROVENANCE, limit=10, now=NOW)
    assert result.manifest.selected == 10 == len(result.records)
    assert result.manifest.candidates == 40
    assert result.manifest.rows_read == 40
    assert result.manifest.provenance.license_status == "unconfirmed"


def test_subset_is_reproducible_and_independent_of_row_order(tmp_path: Path, files: tuple[Path, Path]) -> None:
    first = ingest(*files, provenance=PROVENANCE, limit=12, seed=3, now=NOW)
    ids = [f"P{n:03d}" for n in range(40)]
    random.Random(1).shuffle(ids)
    shuffled = _write(tmp_path / "shuffled.csv", PRODUCT_FIELDS, [_product(pid) for pid in ids])
    second = ingest(shuffled, files[1], provenance=PROVENANCE, limit=12, seed=3, now=NOW)
    assert [r.product_id for r in first.records] == [r.product_id for r in second.records]
    assert first.manifest.subset_checksum == second.manifest.subset_checksum
    other_seed = ingest(*files, provenance=PROVENANCE, limit=12, seed=4, now=NOW)
    assert other_seed.manifest.subset_checksum != first.manifest.subset_checksum


def test_only_judged_products_in_the_small_version_for_the_locale(tmp_path: Path) -> None:
    products = _write(tmp_path / "p.csv", PRODUCT_FIELDS, [_product("A"), _product("B"), _product("C"), _product("D")])
    examples = _write(
        tmp_path / "e.csv",
        EXAMPLE_FIELDS,
        [
            _example("A"),
            _example("B", small="0"),
            _example("C", locale="jp"),
        ],
    )
    result = ingest(products, examples, provenance=PROVENANCE, now=NOW)
    assert [r.product_id for r in result.records] == ["A"]


def test_quarantine_reasons_are_coded_and_never_copy_row_text(tmp_path: Path) -> None:
    rows = [
        _product("OK"),
        _product("NOTITLE", product_title="   "),
        _product("LONG", product_title="x" * 501),
        _product("CTRL", product_description="bad\x00text"),
        _product("JP", product_locale="jp"),
        _product("DUP", product_title="First"),
        _product("DUP", product_title="Second"),
        _product(""),
    ]
    products = _write(tmp_path / "p.csv", PRODUCT_FIELDS, rows)
    examples = _write(
        tmp_path / "e.csv", EXAMPLE_FIELDS, [_example(pid) for pid in ("OK", "NOTITLE", "LONG", "CTRL", "JP", "DUP")]
    )
    result = ingest(products, examples, provenance=PROVENANCE, now=NOW)
    assert [r.product_id for r in result.records] == ["OK"]
    q = result.manifest.quarantined
    assert q["empty_title"] == 1 and q["title_too_long"] == 1 and q["control_characters"] == 1
    assert q["locale_mismatch"] == 1 and q["conflicting_duplicate"] == 1 and q["missing_product_id"] == 1
    assert "bad" not in json.dumps([item.model_dump() for item in result.quarantine])


def test_identical_duplicate_rows_are_kept_once(tmp_path: Path) -> None:
    products = _write(tmp_path / "p.csv", PRODUCT_FIELDS, [_product("A"), _product("A")])
    examples = _write(tmp_path / "e.csv", EXAMPLE_FIELDS, [_example("A")])
    assert ingest(products, examples, provenance=PROVENANCE, now=NOW).manifest.selected == 1


def test_missing_column_fails_loudly(tmp_path: Path) -> None:
    bad = _write(tmp_path / "p.csv", ["product_id", "product_title"], [{"product_id": "A", "product_title": "t"}])
    examples = _write(tmp_path / "e.csv", EXAMPLE_FIELDS, [_example("A")])
    with pytest.raises(IngestError, match="missing columns product_locale"):
        ingest(bad, examples, provenance=PROVENANCE, now=NOW)


def test_jsonl_input_and_unsupported_type(tmp_path: Path, files: tuple[Path, Path]) -> None:
    jsonl = tmp_path / "p.jsonl"
    jsonl.write_text("\n".join(json.dumps(_product(f"P{n:03d}")) for n in range(5)) + "\n", encoding="utf-8")
    assert ingest(jsonl, files[1], provenance=PROVENANCE, now=NOW).manifest.selected == 5
    other = tmp_path / "p.txt"
    other.write_text("x", encoding="utf-8")
    with pytest.raises(IngestError, match="unsupported file type"):
        ingest(other, files[1], provenance=PROVENANCE, now=NOW)


def test_write_then_verify_and_detect_drift(tmp_path: Path, files: tuple[Path, Path]) -> None:
    out = tmp_path / "subset"
    result = ingest(*files, provenance=PROVENANCE, limit=8, now=NOW)
    write_subset(result, out)
    assert verify_subset(out).selected == 8
    with pytest.raises(IngestError, match="already exists"):
        write_subset(result, out)
    lines = (out / "products.jsonl").read_text(encoding="utf-8").splitlines()
    (out / "products.jsonl").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(IngestError, match="count drift"):
        verify_subset(out)


def test_checksum_drift_is_detected_when_a_product_is_swapped(tmp_path: Path, files: tuple[Path, Path]) -> None:
    out = tmp_path / "subset"
    write_subset(ingest(*files, provenance=PROVENANCE, limit=5, now=NOW), out)
    path = out / "products.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    swapped = json.loads(lines[0])
    swapped["product_id"] = "TAMPERED"
    path.write_text("\n".join([json.dumps(swapped), *lines[1:]]) + "\n", encoding="utf-8")
    with pytest.raises(IngestError, match="checksum drift"):
        verify_subset(out)


def test_cli_dry_run_writes_nothing_and_build_then_verify(
    tmp_path: Path, files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    base = [
        "build",
        "--products",
        str(files[0]),
        "--examples",
        str(files[1]),
        "--dataset-version",
        "v0",
        "--limit",
        "6",
    ]
    assert cli_main(base) == 0
    assert "dry run" in capsys.readouterr().out and not out.exists()
    assert cli_main([*base, "--out", str(out)]) == 0
    assert "license_status=unconfirmed" in capsys.readouterr().out
    assert cli_main(["verify", "--out", str(out)]) == 0
    assert cli_main([*base, "--out", str(out)]) == 1


def test_more_than_ten_thousand_products_build_and_verify(tmp_path: Path) -> None:
    # Regression: the checksum used to come from the experience catalog's rebuild module, which caps a
    # collection at 10,000 ids, so the default --limit of 25,000 raised MaintenanceError on any real-sized input.
    ids = [f"B{n:06d}" for n in range(12_000)]
    products = _write(tmp_path / "p.csv", PRODUCT_FIELDS, [_product(pid) for pid in ids])
    examples = _write(tmp_path / "e.csv", EXAMPLE_FIELDS, [_example(pid) for pid in ids])
    result = ingest(products, examples, provenance=PROVENANCE, limit=11_000, now=NOW)
    assert result.manifest.selected == 11_000
    write_subset(result, tmp_path / "subset")
    assert verify_subset(tmp_path / "subset").selected == 11_000


def test_checksum_matches_the_catalog_digest_so_older_manifests_still_verify() -> None:
    from app.indexing.maintenance import checksum_ids as catalog_checksum
    from app.ingest.pipeline import checksum_ids

    assert checksum_ids(["b", "a", "a", "c"]) == catalog_checksum(["a", "b", "c"])


def test_fields_over_the_model_limits_are_quarantined_not_raised(tmp_path: Path) -> None:
    # A 20,001 character description used to escape as a raw pydantic ValidationError and abort the whole build.
    rows = [
        _product("OK"),
        _product("BIGDESC", product_description="d" * 20_001),
        _product("BIGBRAND", product_brand="b" * 256),
        _product("BIGBUL", product_bullet_point="u" * 20_001),
    ]
    products = _write(tmp_path / "p.csv", PRODUCT_FIELDS, rows)
    examples = _write(tmp_path / "e.csv", EXAMPLE_FIELDS, [_example(r["product_id"]) for r in rows])
    result = ingest(products, examples, provenance=PROVENANCE, now=NOW)
    assert [r.product_id for r in result.records] == ["OK"]
    assert result.manifest.quarantined["field_too_long"] == 3
    assert {item.reason for item in result.quarantine} == {"field_too_long"}


def test_csv_cell_larger_than_the_csv_default_limit_is_read(tmp_path: Path) -> None:
    # The csv module's default field limit is 128 KiB; a bigger description raised csv.Error and aborted the build.
    products = _write(
        tmp_path / "p.csv",
        PRODUCT_FIELDS,
        [_product("OK"), _product("HUGE", product_description="h" * 300_000)],
    )
    examples = _write(tmp_path / "e.csv", EXAMPLE_FIELDS, [_example("OK"), _example("HUGE")])
    result = ingest(products, examples, provenance=PROVENANCE, now=NOW)
    assert [r.product_id for r in result.records] == ["OK"]
    assert result.manifest.quarantined["field_too_long"] == 1


def test_a_valid_repeat_of_a_quarantined_row_is_still_selected(tmp_path: Path) -> None:
    # The second pass must apply the same validation as the first, not take the first row it sees for an id.
    rows = [_product("DUP", product_title=""), _product("DUP", product_title="Real title")]
    products = _write(tmp_path / "p.csv", PRODUCT_FIELDS, rows)
    examples = _write(tmp_path / "e.csv", EXAMPLE_FIELDS, [_example("DUP")])
    result = ingest(products, examples, provenance=PROVENANCE, now=NOW)
    assert [(r.product_id, r.title) for r in result.records] == [("DUP", "Real title")]
    assert result.manifest.quarantined["empty_title"] == 1


def test_jsonl_numbers_and_nulls_are_read_like_csv_cells(tmp_path: Path) -> None:
    products = tmp_path / "p.jsonl"
    products.write_text(
        json.dumps({**_product("A"), "product_brand": None, "product_color": None}) + "\n", encoding="utf-8"
    )
    examples = tmp_path / "e.jsonl"
    examples.write_text(json.dumps({**_example("A"), "small_version": 1.0}) + "\n", encoding="utf-8")
    result = ingest(products, examples, provenance=PROVENANCE, now=NOW)
    assert [(r.product_id, r.brand, r.color) for r in result.records] == [("A", "", "")]
