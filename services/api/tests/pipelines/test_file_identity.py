"""A file's identity is its full path; its base name is only for display.

Found by reading ``process_batch`` against Ray: ``read_binary_files(include_paths=True)`` yields a ``path`` column and
no ``filename``, so the old ``batch["filename"]`` raised KeyError on the first batch. Fixing that by taking the base name
alone would have let two files in different folders share an identity, and the sinks derive chunk IDs and the
stale-chunk sweep from it.
"""

from __future__ import annotations

import pytest

from pipelines.ingestion.identity import file_identity


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("bucket/docs/a/guide.pdf", ("bucket/docs/a/guide.pdf", "guide.pdf")),
        ("s3://bucket/docs/guide.pdf", ("bucket/docs/guide.pdf", "guide.pdf")),
        ("S3A://bucket/guide.pdf", ("bucket/guide.pdf", "guide.pdf")),
        ("  bucket/guide.pdf  ", ("bucket/guide.pdf", "guide.pdf")),
        ("guide.pdf", ("guide.pdf", "guide.pdf")),
    ],
)
def test_identity_is_the_path_and_display_is_the_base_name(path: str, expected: tuple[str, str]) -> None:
    assert file_identity(path) == expected


@pytest.mark.parametrize("path", ["", "   ", "s3://", "bucket/folder/", "s3://bucket/"])
def test_a_path_that_names_no_file_is_refused(path: str) -> None:
    with pytest.raises(ValueError, match="cannot identify a file"):
        file_identity(path)


def _chunk(source_path: str | None, filename: str = "guide.pdf") -> dict:
    metadata = {"filename": filename, "page_number": 1, "chunk_index": 0, "chunk_hash": "abc"}
    if source_path is not None:
        metadata["source_path"] = source_path
    return {"text": "reset your password", "vector": [0.1, 0.2, 0.3, 0.4], "metadata": metadata}


def test_qdrant_point_ids_differ_for_same_named_files_in_different_folders() -> None:
    from pipelines.ingestion.indexing.qdrant import QdrantIndexer

    indexer = QdrantIndexer("acme")

    def point(row: dict) -> str:
        payload = {
            "text": row["text"],
            "content_type": "text",
            "filename": row["metadata"]["filename"],
            "source_path": row["metadata"].get("source_path"),
            "page": 1,
        }
        return indexer._point_id(row, payload)

    a = point(_chunk("bucket/eu/guide.pdf"))
    b = point(_chunk("bucket/us/guide.pdf"))
    assert a != b
    assert a == point(_chunk("bucket/eu/guide.pdf"))  # re-ingesting the same file is idempotent
    assert point(_chunk(None)) == point(_chunk(None))  # a row with no path still keys on its file name
