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
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.indexing.maintenance import checksum_ids
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
MANIFEST_NAME = "manifest.json"
PRODUCTS_NAME = "products.jsonl"
QUARANTINE_NAME = "quarantine.jsonl"


class IngestError(ValueError):
    """Raised for unreadable inputs, missing columns, or a subset that fails verification."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_rows(path: Path, required: tuple[str, ...]) -> Iterator[dict[str, str]]:
    """Yield rows from .csv or .jsonl; .parquet needs pyarrow, which is not a dependency of this service."""
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq  # noqa: PLC0415
        except ImportError as exc:
            raise IngestError("reading .parquet needs pyarrow; convert to CSV or install pyarrow locally") from exc
        table = pq.read_table(path)
        _require(set(table.column_names), required, path)
        for row in table.to_pylist():
            yield {key: "" if value is None else str(value) for key, value in row.items()}
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            _require(set(reader.fieldnames or ()), required, path)
            for row in reader:
                yield {key: value or "" for key, value in row.items() if key is not None}
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
                yield {key: "" if value is None else str(value) for key, value in row.items()}
    else:
        raise IngestError(f"unsupported file type: {path.suffix or path.name}")


def _require(present: set[str], required: tuple[str, ...], path: Path) -> None:
    missing = [name for name in required if name not in present]
    if missing:
        raise IngestError(f"{path.name}: missing columns {', '.join(missing)}")


def _rank(seed: int, product_id: str) -> str:
    return hashlib.sha256(f"{seed}:{product_id}".encode("utf-8")).hexdigest()


def _has_control_characters(*values: str) -> bool:
    return any(ch != "\n" and ch != "\t" and (ord(ch) < 32 or ord(ch) == 127) for value in values for ch in value)


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
    for row in read_rows(examples_path, EXAMPLE_COLUMNS):
        if row["product_locale"].strip().lower() == locale.lower() and row["small_version"].strip() == "1":
            judged.add(row["product_id"].strip())

    quarantined: list[QuarantinedRow] = []
    rows_read = 0
    first_seen: dict[str, ProductRecord] = {}
    conflicts: set[str] = set()
    for row in read_rows(products_path, REQUIRED_PRODUCT_COLUMNS):
        rows_read += 1
        product_id = row.get(PRODUCT_COLUMNS["product_id"], "").strip()
        if not product_id:
            quarantined.append(QuarantinedRow(product_id="", reason="missing_product_id"))
            continue
        if product_id not in judged:
            continue
        reason = None
        title = row.get(PRODUCT_COLUMNS["title"], "").strip()
        row_locale = row.get(PRODUCT_COLUMNS["locale"], "").strip().lower()
        fields = {name: row.get(column, "").strip() for name, column in PRODUCT_COLUMNS.items()}
        if row_locale != locale.lower():
            reason = "locale_mismatch"
        elif not title:
            reason = "empty_title"
        elif len(title) > MAX_TITLE:
            reason = "title_too_long"
        elif _has_control_characters(*fields.values()):
            reason = "control_characters"
        if reason:
            quarantined.append(QuarantinedRow(product_id=product_id, reason=reason))
            continue
        record = ProductRecord(**{**fields, "locale": row_locale})
        previous = first_seen.get(product_id)
        if previous is None:
            first_seen[product_id] = record
        elif previous != record:
            conflicts.add(product_id)

    for product_id in sorted(conflicts):
        first_seen.pop(product_id, None)
        quarantined.append(QuarantinedRow(product_id=product_id, reason="conflicting_duplicate"))

    ordered = sorted(first_seen, key=lambda pid: (_rank(seed, pid), pid))[:limit]
    records = tuple(first_seen[pid] for pid in ordered)
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
        candidates=len(first_seen),
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
