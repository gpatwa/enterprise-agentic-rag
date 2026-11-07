"""Read ESCI-shaped CSV or JSONL files into a validated, reproducible product subset.

The subset is chosen by hashing ``seed:product_id`` so the same inputs always give the same products,
whatever order the rows arrive in. Nothing is written unless ``write_subset`` is called, and the data
itself is never part of the repository. Column names follow the ESCI files as recalled and must be
confirmed against the real download; a missing column fails loudly rather than guessing.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from app.ingest.models import (
    QUARANTINE_REASONS,
    IngestManifest,
    IngestResult,
    ProductProvenance,
    ProductRecord,
    QuarantinedRow,
)

PRODUCT_COLUMNS = {
    "product_id": "product_id",
    "locale": "product_locale",
    "title": "product_title",
    "description": "product_description",
    "bullets": "product_bullet_point",
    "brand": "product_brand",
    "color": "product_color",
}
EXAMPLE_COLUMNS = ("product_id", "product_locale", "small_version")
REQUIRED_PRODUCT_COLUMNS = ("product_id", "product_locale", "product_title")
MAX_TITLE = 500
# Mirrors the length limits on ProductRecord, so an over-long field is quarantined instead of raising.
FIELD_LIMITS = {"product_id": 128, "description": 20000, "bullets": 20000, "brand": 255, "color": 255}
MANIFEST_NAME = "manifest.json"
PRODUCTS_NAME = "products.jsonl"
QUARANTINE_NAME = "quarantine.jsonl"


class IngestError(ValueError):
    """Raised for unreadable inputs, missing columns, or a subset that fails verification."""


def checksum_ids(product_ids: Iterable[str]) -> str:
    """SHA-256 over the sorted, unique ids joined by newlines.

    This is the same digest as ``app.indexing.maintenance.checksum_ids`` (so manifests built before this function
    existed still verify) without that module's 10,000-document cap, which belongs to the experience catalog's
    rebuild manifests and made every product build above 10,000 products, including the default 25,000, fail.
    """
    return hashlib.sha256("\n".join(sorted(set(product_ids))).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


PARQUET_BATCH_ROWS = 20_000
CSV_FIELD_LIMIT = 1 << 24  # the csv module's default (128 KiB) is smaller than some real product descriptions


def _cell(value: object) -> str:
    """Render one Parquet or JSON value as the string a CSV cell would hold: None and NaN are empty, bools and
    whole floats (a flag column stored as float64 because of nulls) lose their ``True`` / ``.0`` spelling."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        return str(int(value)) if value.is_integer() else str(value)
    return str(value)


def read_rows(
    path: Path, required: tuple[str, ...], columns: tuple[str, ...] | None = None
) -> Iterator[dict[str, str]]:
    """Yield rows from .csv, .jsonl or .parquet as string dicts.

    ``columns`` limits which Parquet columns are decoded. Parquet is streamed in record batches, so memory is
    bounded by the batch size and not by the file. .parquet needs pyarrow, which is not a dependency of this service.
    """
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        try:
            import pyarrow as pa  # noqa: PLC0415
            import pyarrow.parquet as pq  # noqa: PLC0415
        except ImportError as exc:
            raise IngestError("reading .parquet needs pyarrow; convert to CSV or install pyarrow locally") from exc
        try:
            with pq.ParquetFile(path) as parquet:
                names = list(parquet.schema_arrow.names)
                _require(set(names), required, path)
                wanted = [name for name in (columns or names) if name in names]
                for batch in parquet.iter_batches(batch_size=PARQUET_BATCH_ROWS, columns=wanted):
                    for row in batch.to_pylist():
                        yield {key: _cell(value) for key, value in row.items()}
        except (OSError, pa.ArrowException) as exc:
            raise IngestError(f"{path.name}: unreadable parquet file ({type(exc).__name__})") from exc
    elif suffix == ".csv":
        csv.field_size_limit(CSV_FIELD_LIMIT)
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            _require(set(reader.fieldnames or ()), required, path)
            try:
                for row in reader:
                    yield {key: value or "" for key, value in row.items() if key is not None}
            except csv.Error as exc:
                raise IngestError(f"{path.name}: unreadable CSV near line {reader.line_num} ({exc})") from exc
    elif suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise IngestError(f"{path.name}: line {number} is not valid JSON") from exc
                if number == 1:
                    _require(set(row), required, path)
                yield {key: _cell(value) for key, value in row.items()}
    else:
        raise IngestError(f"unsupported file type: {path.suffix or path.name}")


def _require(present: set[str], required: tuple[str, ...], path: Path) -> None:
    missing = [name for name in required if name not in present]
    if missing:
        raise IngestError(f"{path.name}: missing columns {', '.join(missing)}")


def _rank(seed: int, product_id: str) -> str:
    return hashlib.sha256(f"{seed}:{product_id}".encode("utf-8")).hexdigest()


_CONTROL_CHARACTERS = re.compile("[\x00-\x08\x0b-\x1f\x7f]")  # every C0 control and DEL except tab and newline


def _has_control_characters(*values: str) -> bool:
    return any(_CONTROL_CHARACTERS.search(value) for value in values)


def _classify(row: dict[str, str], locale: str, judged: set[str]) -> tuple[str, str | None, dict[str, str] | None]:
    """Return ``(product_id, quarantine reason, validated fields)`` for one product row.

    Rows for products that were not judged return no reason and no fields. A quarantined row returns a reason
    and no fields, and a valid row returns fields and no reason.
    """
    product_id = row.get(PRODUCT_COLUMNS["product_id"], "").strip()
    if not product_id:
        return "", "missing_product_id", None
    if product_id not in judged:
        return product_id, None, None
    fields = {name: row.get(column, "").strip() for name, column in PRODUCT_COLUMNS.items()}
    fields["locale"] = fields["locale"].lower()
    if fields["locale"] != locale.lower():
        reason = "locale_mismatch"
    elif not fields["title"]:
        reason = "empty_title"
    elif len(fields["title"]) > MAX_TITLE:
        reason = "title_too_long"
    elif _has_control_characters(*fields.values()):
        reason = "control_characters"
    elif any(len(fields[name]) > cap for name, cap in FIELD_LIMITS.items()):
        reason = "field_too_long"
    else:
        return product_id, None, fields
    return product_id, reason, None


def ingest(
    products_path: Path,
    examples_path: Path,
    *,
    provenance: ProductProvenance,
    locale: str = "us",
    limit: int = 25000,
    seed: int = 7,
    now: datetime | None = None,
) -> IngestResult:
    """Select up to ``limit`` products judged in the small version for ``locale`` and validate them."""
    if limit < 1:
        raise IngestError("limit must be at least 1")
    created_at = now or datetime.now(timezone.utc)

    judged: set[str] = set()
    for row in read_rows(examples_path, EXAMPLE_COLUMNS, EXAMPLE_COLUMNS):
        if row["product_locale"].strip().lower() == locale.lower() and row["small_version"].strip() == "1":
            judged.add(row["product_id"].strip())

    # Pass 1 keeps only a 16-byte fingerprint per candidate (enough to spot conflicting duplicates), so memory
    # follows the number of candidate ids, not their text. Pass 2 materializes just the selected products.
    quarantined: list[QuarantinedRow] = []
    rows_read = 0
    fingerprints: dict[str, bytes] = {}
    conflicts: set[str] = set()
    columns = tuple(PRODUCT_COLUMNS.values())
    for row in read_rows(products_path, REQUIRED_PRODUCT_COLUMNS, columns):
        rows_read += 1
        product_id, reason, fields = _classify(row, locale, judged)
        if reason:
            quarantined.append(QuarantinedRow(product_id=product_id, reason=reason))
        elif fields is not None:
            fingerprint = hashlib.blake2b("\x1f".join(fields.values()).encode("utf-8"), digest_size=16).digest()
            previous = fingerprints.setdefault(product_id, fingerprint)
            if previous != fingerprint:
                conflicts.add(product_id)

    for product_id in sorted(conflicts):
        del fingerprints[product_id]
        quarantined.append(QuarantinedRow(product_id=product_id, reason="conflicting_duplicate"))

    ordered = sorted(fingerprints, key=lambda pid: (_rank(seed, pid), pid))[:limit]
    wanted = set(ordered)
    chosen: dict[str, ProductRecord] = {}
    for row in read_rows(products_path, REQUIRED_PRODUCT_COLUMNS, columns):
        if len(chosen) == len(wanted):
            break
        product_id, reason, fields = _classify(row, locale, wanted)
        if fields is not None and not reason and product_id not in chosen:
            chosen[product_id] = ProductRecord(**fields)
    if len(chosen) != len(wanted):
        raise IngestError(f"{products_path.name} changed while it was being read; run the build again")
    records = tuple(chosen[pid] for pid in ordered)
    counts = {reason: 0 for reason in QUARANTINE_REASONS}
    for item in quarantined:
        counts[item.reason] += 1
    manifest = IngestManifest(
        provenance=provenance,
        locale=locale.lower(),
        limit=limit,
        seed=seed,
        products_file_sha256=sha256_file(products_path),
        examples_file_sha256=sha256_file(examples_path),
        rows_read=rows_read,
        candidates=len(fingerprints),
        selected=len(records),
        quarantined=counts,
        subset_checksum=checksum_ids(record.product_id for record in records),
        created_at=created_at,
    )
    return IngestResult(records=records, quarantine=tuple(quarantined), manifest=manifest)


def write_subset(result: IngestResult, out_dir: Path) -> None:
    """Write products, quarantine and manifest. Refuses to overwrite an existing subset."""
    manifest_path = out_dir / MANIFEST_NAME
    if manifest_path.exists():
        raise IngestError(f"{manifest_path} already exists; choose a new directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / PRODUCTS_NAME).open("w", encoding="utf-8") as handle:
        for record in result.records:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n")
    with (out_dir / QUARANTINE_NAME).open("w", encoding="utf-8") as handle:
        for item in result.quarantine:
            handle.write(json.dumps(item.model_dump(mode="json"), sort_keys=True) + "\n")
    manifest_path.write_text(result.manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def verify_subset(out_dir: Path) -> IngestManifest:
    """Re-read a written subset and confirm it still matches its manifest; raise IngestError on any drift."""
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise IngestError(f"{manifest_path} not found")
    manifest = IngestManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    ids: list[str] = []
    with (out_dir / PRODUCTS_NAME).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                ids.append(ProductRecord.model_validate_json(line).product_id)
    if len(ids) != manifest.selected:
        raise IngestError(f"count drift: manifest says {manifest.selected}, file has {len(ids)}")
    if len(set(ids)) != len(ids):
        raise IngestError("duplicate product ids in subset")
    if checksum_ids(ids) != manifest.subset_checksum:
        raise IngestError("checksum drift: the subset no longer matches its manifest")
    return manifest
