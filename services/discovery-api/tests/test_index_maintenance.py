from __future__ import annotations

import pytest

from app.indexing.maintenance import (
    ChecksumMismatch,
    DryRunRequired,
    IndexMaintenance,
    Tombstone,
    checksum_ids,
)


def test_rebuild_is_bounded_immutable_and_excludes_tombstones() -> None:
    maintenance = IndexMaintenance()
    tombstone = Tombstone("gone", "tenant-a", "policy", "catalog-v2")

    maintenance.preview_tombstone(tombstone)
    maintenance.apply_tombstone(tombstone, dry_run=True)
    maintenance.apply_tombstone(tombstone)
    manifest = maintenance.preview_rebuild("generation-1", ["b", "gone", "a"])

    assert manifest.document_ids == ("a", "b")
    assert manifest.document_count == 2
    assert manifest.tombstone_count == 1
    maintenance.apply_rebuild(manifest, dry_run=True)
    maintenance.apply_rebuild(manifest)
    assert maintenance.generations["generation-1"] == ("a", "b")


def test_destructive_operations_require_preview_and_support_dry_run() -> None:
    maintenance = IndexMaintenance()
    manifest = maintenance.preview_rebuild("generation-1", ["a"])

    with pytest.raises(DryRunRequired):
        maintenance.apply_rebuild(manifest)
    maintenance.apply_rebuild(manifest, dry_run=True)
    assert maintenance.generations == {}
    maintenance.apply_rebuild(manifest)

    maintenance.preview_swap("generation-1")
    maintenance.apply_swap("generation-1", dry_run=True)
    assert "imd-catalog-read" not in maintenance.aliases
    maintenance.apply_swap("generation-1")
    assert maintenance.aliases["imd-catalog-read"].generation == "generation-1"


def test_reconciliation_rejects_bad_checksum_and_reports_mismatch() -> None:
    maintenance = IndexMaintenance()
    manifest = maintenance.preview_rebuild("generation-1", ["a", "b"])
    maintenance.apply_rebuild(manifest, dry_run=True)
    maintenance.apply_rebuild(manifest)

    with pytest.raises(ChecksumMismatch):
        maintenance.reconcile("generation-1", ["a", "b"], expected_checksum="0" * 64)
    result = maintenance.reconcile("generation-1", ["a", "c"])
    assert result.matches is False
    assert result.missing_count == 1
    assert result.unexpected_count == 1


def test_rollback_returns_to_prior_validated_alias_and_checksum_is_stable() -> None:
    maintenance = IndexMaintenance()
    first = maintenance.preview_rebuild("generation-1", ["a"])
    maintenance.apply_rebuild(first, dry_run=True)
    maintenance.apply_rebuild(first)
    second = maintenance.preview_rebuild("generation-2", ["b"])
    maintenance.apply_rebuild(second, dry_run=True)
    maintenance.apply_rebuild(second)
    maintenance.preview_swap("generation-1")
    maintenance.apply_swap("generation-1", dry_run=True)
    maintenance.apply_swap("generation-1")
    maintenance.preview_swap("generation-2")
    maintenance.apply_swap("generation-2", dry_run=True)
    maintenance.apply_swap("generation-2")
    maintenance.preview_rollback()
    maintenance.apply_rollback(dry_run=True)
    maintenance.apply_rollback()

    assert maintenance.aliases["imd-catalog-read"].generation == "generation-1"
    assert checksum_ids(["b", "a", "a"]) == checksum_ids(["a", "b"])
